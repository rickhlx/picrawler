"""Telegram in and out for Petronilo, stdlib only (urllib.request, json): no
new package on the Pi.

Lets the owner text him from anywhere without the wake word, and gives him a
way to speak up on his own (a scheduled reminder, a low battery warning) via
``send``, which is what gets wired up as ``va.notify``.

Long-polls getUpdates in a background thread. Each incoming message that
reaches the agent runs on its own thread, so one slow answer doesn't block
polling for the next message; polling itself is single-threaded, offset
tracking is not shared with anything else.
"""
import json
import threading
import time
import urllib.error
import urllib.parse
import urllib.request

from control import job_list, status_dict

API_ROOT = "https://api.telegram.org/bot{token}/{method}"
POLL_TIMEOUT = 30
MAX_MESSAGE_LEN = 4000
STRANGER_REPLY = "No te conozco, mijo. Tu chat id es {chat_id}."
START_REPLY = "Orale, ya te tengo agendado, mijo. Escribeme cuando quieras."


class TelegramBridge:
    """Bridges one Telegram bot to a VoiceActiveCrawler (``va``). ``chat_ids``
    is the allowlist of chats that may talk to him; messages from anywhere
    else get one explanatory reply and are ignored after that."""

    def __init__(self, token, chat_ids, va, speak_replies=False):
        self.token = token
        self.chat_ids = set(chat_ids)
        self.va = va
        self.speak_replies = speak_replies
        self._offset = 0
        self._running = False
        self._thread = None
        self._greeted_strangers = set()

    def start(self):
        self._running = True
        self._thread = threading.Thread(target=self._poll_loop, daemon=True)
        self._thread.start()

    def stop(self):
        self._running = False

    # ── outgoing ──────────────────────────────────────────────────────

    def send(self, text, chat_id=None):
        """Send text to one chat, or every allowed chat if chat_id is None.
        Cheap and silent when there is nobody to send to; never raises."""
        if not self.chat_ids:
            return
        targets = [chat_id] if chat_id is not None else list(self.chat_ids)
        for target in targets:
            try:
                for chunk in self._split(text):
                    self._call("sendMessage", {"chat_id": target, "text": chunk})
            except Exception as e:
                print(f"(telegram: {self._redact(e)})")

    @staticmethod
    def _split(text):
        text = text or ""
        if len(text) <= MAX_MESSAGE_LEN:
            return [text]
        return [text[i:i + MAX_MESSAGE_LEN] for i in range(0, len(text), MAX_MESSAGE_LEN)]

    def _call(self, method, params):
        url = API_ROOT.format(token=self.token, method=method)
        data = urllib.parse.urlencode(params).encode("utf-8")
        with urllib.request.urlopen(url, data=data, timeout=POLL_TIMEOUT + 10) as resp:
            return json.loads(resp.read().decode("utf-8"))

    def _redact(self, error):
        # str(e) on a urllib error can include the request URL, which has the
        # token in it: never let that reach a log line.
        return str(error).replace(self.token, "<token>")

    # ── incoming ──────────────────────────────────────────────────────

    def _poll_loop(self):
        backoff = 5
        while self._running:
            try:
                payload = self._get_updates()
                backoff = 5
            except Exception as e:
                print(f"(telegram: {self._redact(e)})")
                time.sleep(backoff)
                backoff = min(backoff * 2, 60)
                continue
            for update in payload.get("result", []):
                self._offset = max(self._offset, update.get("update_id", 0) + 1)
                threading.Thread(target=self._handle_update, args=(update,), daemon=True).start()

    def _get_updates(self):
        params = {"timeout": POLL_TIMEOUT, "offset": self._offset}
        url = API_ROOT.format(token=self.token, method="getUpdates") + "?" + urllib.parse.urlencode(params)
        with urllib.request.urlopen(url, timeout=POLL_TIMEOUT + 10) as resp:
            return json.loads(resp.read().decode("utf-8"))

    def _handle_update(self, update):
        try:
            message = update.get("message") or {}
            chat = message.get("chat") or {}
            chat_id = chat.get("id")
            text = (message.get("text") or "").strip()
            if chat_id is None or not text:
                return
            if chat_id not in self.chat_ids:
                if chat_id not in self._greeted_strangers:
                    self._greeted_strangers.add(chat_id)
                    self.send(STRANGER_REPLY.format(chat_id=chat_id), chat_id)
                return
            first_name = (message.get("from") or {}).get("first_name", "")
            self._handle_allowed(chat_id, first_name, text)
        except Exception as e:
            print(f"(telegram: {self._redact(e)})")

    def _handle_allowed(self, chat_id, first_name, text):
        if text == "/start":
            self.send(START_REPLY, chat_id)
            return
        if text == "/stop":
            self.va.stop_speaking()
            self.send("Ya pare.", chat_id)
            return
        if text == "/jobs":
            jobs = job_list(self.va)
            self.send("\n".join(jobs) if jobs else "(no tengo pendientes)", chat_id)
            return
        if text == "/status":
            status = status_dict(self.va)
            self.send("\n".join(f"{key}: {value}" for key, value in status.items()), chat_id)
            return
        prompt = (f"Mensaje por Telegram de {first_name}: {text}\n"
                  "Contestale por escrito, corto, sin moverte.")
        reply = self.va.run_task(prompt, speak=self.speak_replies)
        self.send(reply, chat_id)
