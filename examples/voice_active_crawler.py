from picrawler.voice_assistant import VoiceAssistant
from picrawler import Picrawler
from memory import Memory
import time
import queue
import threading
import concurrent.futures
import datetime
import os
import random
import re
import sys

# Spanish weekday/month names for the "## Ahora" prompt section (datetime.weekday(): 0=Monday)
_WEEKDAYS_ES = ("lunes", "martes", "miércoles", "jueves", "viernes", "sábado", "domingo")
_MONTHS_ES = ("enero", "febrero", "marzo", "abril", "mayo", "junio", "julio", "agosto",
              "septiembre", "octubre", "noviembre", "diciembre")


class BargeIn:
    """Listens for the wake word while he speaks, so "compa" cuts him off.

    Runs on its own daemon thread with the offline recogniser only
    (``stt.listen(stream=False)`` is Vosk; the paid transcription is never
    called). The mic is a USB capture device separate from the HAT speaker
    (docs/pi-config.md, Audio), so it can stay open during playback. What it
    hears is mostly his own voice, so only the wake word itself counts, as a
    whole word, none of the loose WAKE_ALIASES ("com", "compra").

    ``stop()`` must run before anyone else opens the mic (the follow-up
    ``listen()``): it sets ``stt.stop_listening_event`` until the thread has
    left ``listen()`` and joined, since ``listen()`` clears that event when
    it starts and a single set could land in the gap between two calls."""

    def __init__(self, stt, wake_words, on_hit, norm=lambda t: " ".join((t or "").lower().split())):
        self.stt = stt
        self.norm = norm
        self.patterns = [re.compile(r"\b" + re.escape(norm(w)) + r"\b")
                         for w in (wake_words or []) if norm(w)]
        self.on_hit = on_hit
        self.hit = False
        self._stop = threading.Event()
        self._thread = None

    def start(self):
        if self._thread is not None and self._thread.is_alive():
            return
        self.hit = False
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, name="barge_in", daemon=True)
        self._thread.start()

    def stop(self, timeout=3.0):
        """Stop listening and release the mic; blocks until the thread is done
        (or ``timeout``)."""
        self._stop.set()
        t, self._thread = self._thread, None
        if t is None or not t.is_alive():
            return
        deadline = time.time() + timeout
        while t.is_alive() and time.time() < deadline:
            try:
                self.stt.stop_listening()
            except Exception:
                pass
            t.join(0.2)
        if t.is_alive():
            print("(interrupción: el micrófono no se soltó a tiempo)")
            return
        # drop whatever of his own voice the recogniser was still chewing on
        rec = getattr(self.stt, "recognizer", None)
        if rec is not None and callable(getattr(rec, "Reset", None)):
            try:
                rec.Reset()
            except Exception:
                pass

    def matches(self, text):
        heard = self.norm(text)
        return bool(heard) and any(p.search(heard) for p in self.patterns)

    def _run(self):
        # after a keyboard trigger the library's wake-word thread may still be
        # closing the mic: let it finish rather than open the device twice
        wake_thread = getattr(self.stt, "wake_word_thread", None)
        if wake_thread is not None and wake_thread is not threading.current_thread():
            try:
                wake_thread.join(2.0)
            except RuntimeError:
                pass
        while not self._stop.is_set():
            try:
                text = self.stt.listen(stream=False)
            except Exception as e:
                print(f"(interrupción: el micrófono falló: {e})")
                return
            if self._stop.is_set():
                return
            if text and self.matches(text):
                self.hit = True
                print("\n(me interrumpieron)", flush=True)
                try:
                    self.on_hit()
                except Exception as e:
                    print(f"(interrupción falló: {e})")
                return


class VoiceActiveCrawler(VoiceAssistant):

    # how long he listens for the new question after being interrupted when
    # follow_up_seconds is off
    BARGE_IN_LISTEN_SECONDS = 8

    ACTION_MAP = {
        "forward":      ("do_action", {"motion_name": "forward", "step": 1, "speed": 70}),
        "backward":     ("do_action", {"motion_name": "backward", "step": 1, "speed": 70}),
        "turn left":    ("do_action", {"motion_name": "turn left", "step": 1, "speed": 70}),
        "turn right":   ("do_action", {"motion_name": "turn right", "step": 1, "speed": 70}),
        "sit":          ("do_action", {"motion_name": "sit", "step": 1, "speed": 50}),
        "stand":        ("do_action", {"motion_name": "stand", "step": 1, "speed": 50}),
        "wave":         ("do_action", {"motion_name": "wave", "step": 1, "speed": 60}),
        "push up":      ("do_action", {"motion_name": "push_up", "step": 1, "speed": 50}),
        "twerk":        ("self:party", {"seconds": 12}),   # reggaeton routine from twerk.py
        "trot":         ("self:trot", {"half_cycles": 10}),  # fast diagonal-pair gait, forward
        "look left":    ("do_action", {"motion_name": "look_left", "step": 1, "speed": 60}),
        "look right":   ("do_action", {"motion_name": "look_right", "step": 1, "speed": 60}),
        "look up":      ("do_action", {"motion_name": "look_up", "step": 1, "speed": 60}),
        "look down":    ("do_action", {"motion_name": "look_down", "step": 1, "speed": 60}),
        # crowd-pleasers from picrawler/tricks.py
        "bow":          ("self:trick", {"name": "bow"}),
        "nod":          ("self:trick", {"name": "nod"}),
        "shake head":   ("self:trick", {"name": "shake head"}),
        "shimmy":       ("self:trick", {"name": "shimmy"}),
        "hula":         ("self:trick", {"name": "hula"}),
        "bounce":       ("self:trick", {"name": "bounce"}),
        "spin":         ("self:trick", {"name": "spin"}),
        "play dead":    ("self:trick", {"name": "play dead"}),
        "high five":    ("self:trick", {"name": "high five"}),
    }

    def __init__(self, *args, stt=None, follow_up_seconds=0, end_phrases=None, farewell="",
                 stream_speech=True, memory_dir=None, memory_llm=None, greet_with_vision=False,
                 battery_low_volts=7.3, battery_warning="", move_speed_limit=100, max_actions=None,
                 fidget_every=None, locator=None, sonar=None, find_phrases=None, brain=None,
                 brain_error_phrase="Se me fue la señal, mijo. Pregúntame otra vez en un ratito.",
                 budget_phrase="Ya gasté mi domingo de hoy, mijo. Mañana seguimos platicando.",
                 scheduler=None, notify=None, task_wait_seconds=600, barge_in=False,
                 **kwargs):
        self.action_queue = queue.Queue()
        # Autonomous turns (reminders, tasks from a control socket or Telegram) outside
        # any wake-word conversation. scheduler: Scheduler with pop_due()/describe() (see
        # scheduler.py); notify: callable(text) to mirror what he says on his own to a
        # text channel; task_wait_seconds: how long an autonomous turn waits for an
        # ongoing conversation to end before giving up.
        self.scheduler = scheduler
        self.notify = notify
        self.task_wait_seconds = task_wait_seconds
        # Set at the end of on_start and whenever a conversation ends; cleared in on_wake.
        # A conversation spans on_wake..._end_conversation.
        self._idle = threading.Event()
        # Serializes autonomous turns; on_wake acquires/releases this first thing, so a
        # wake word waits for a running task to finish (a few seconds at most).
        self._task_lock = threading.Lock()
        # The SpeechPipeline currently speaking, if any (conversation or autonomous turn).
        self._pipeline = None
        self._prompt_lock = threading.Lock()
        # Bumped at every wake word, so the thread that closes a conversation can tell
        # whether a new one started before it got to mark him idle.
        self._conversation = 0
        # Agent brain (petronilo_agent.AgentBrain): replies come from a Claude
        # agent with shell, skills, MCP and robot tools instead of self.llm,
        # which then only serves the base class. None = plain LLM + ACTIONS: line.
        self.brain = brain
        # Said when the agent brain (or its LLM fallback) fails after it has
        # already started talking, and when the day's spend cap is hit.
        self.brain_error_phrase = brain_error_phrase
        self.budget_phrase = budget_phrase
        self._tool_moves = 0
        # Calm body while talking: every move capped at this speed, and at most
        # max_actions per reply. The amp and the servos share the HAT 5 V rail.
        self.move_speed_limit = move_speed_limit
        self.max_actions = max_actions
        self._action_busy = threading.Event()
        # Small idle gestures while he talks, one every fidget_every=(min, max)
        # seconds when no action is running (None = keep still).
        self.fidget_every = fidget_every
        self._talking = threading.Event()
        self._next_fidget = 0.0
        # Speak sentence-by-sentence while the LLM is still streaming (needs PetroniloTTS)
        self.stream_speech = stream_speech
        self._spoken_result = None
        # Long-term memory, learned from each conversation once it ends (needs memory_llm)
        memory_dir = memory_dir or os.path.join(os.path.dirname(os.path.abspath(__file__)), "petronilo_memory")
        self.memory = Memory(memory_dir, llm=memory_llm, name=kwargs.get("name", "the robot"))
        self._transcript = []     # (role, text) turns of the current conversation
        self._recording = True    # off for turns that are not part of the conversation
        # Vision greeting on wake (opt-in: adds ~3s before listening)
        self.greet_with_vision = greet_with_vision
        if greet_with_vision:
            kwargs["answer_on_wake"] = ""
        # Battery watch
        self.battery_low_volts = battery_low_volts
        self.battery_warning = battery_warning
        self._last_battery_warning = 0.0
        self._last_volts = None   # from the last _report_battery (wake word, start-up)
        # "find <object>": camera + vision model to spot it, sonar to stop short (seeker.py)
        self.locator = locator
        self.sonar = sonar
        self.find_phrases = {**self.FIND_PHRASES, **(find_phrases or {})}
        self._announcements = []  # said once the round's actions finish
        # Conversation mode: after answering, keep listening this many seconds
        # for the next question without requiring the wake word (0 = off).
        self.follow_up_seconds = follow_up_seconds
        self.end_phrases = [self._norm_text(x) for x in (end_phrases or [])]
        self.farewell = farewell
        self._action_thread = None
        self._action_running = False
        try:
            super().__init__(*args, **kwargs)
        except Exception as e:
            self._handle_init_error(e)
            raise
        # LLM.add_message trims history from the front once it passes max_messages,
        # which drops the system prompt. Trim it ourselves instead and keep the
        # system prompt pinned at index 0 (see _refresh_system_prompt).
        self._system_msg = self.llm.messages[0]
        self._history_limit = self.llm.max_messages
        self.llm.max_messages = sys.maxsize
        self._init_crawler()
        if stt is not None:
            # Replace the library's STT (e.g. with HybridSTT from petronilo_voice)
            self.stt = stt
            self.stt.set_wake_words(self.wake_word)
        # The small Vosk models often garble short wake phrases; match loosely
        # (accent-insensitive, wake phrase anywhere in the transcript) instead
        # of the library's exact whole-transcript comparison.
        self.stt.heard_wake_word = self._fuzzy_heard_wake_word
        # Barge-in (opt-in): while he speaks in a conversation, a BargeIn thread
        # listens for the exact wake word; a hit cancels the speech, cuts the
        # brain's turn and _follow_up listens for the new question right away.
        self._interrupted = False
        self._barge = None
        if barge_in:
            if callable(getattr(self.stt, "listen", None)) and callable(getattr(self.stt, "stop_listening", None)):
                self._barge = BargeIn(self.stt, self.wake_word, self._on_barge_in, norm=self._norm_text)
            else:
                print("(interrupción por voz desactivada: el STT no tiene reconocedor local)")
        if brain is not None:
            brain.attach(self)

    @staticmethod
    def _handle_init_error(error):
        err_msg = str(error)
        if 'PortAudioError' in type(error).__name__ or 'query_devices' in err_msg:
            print("=" * 55)
            print("  No microphone detected!")
            print("  The voice assistant requires a microphone for")
            print("  speech recognition and wake word detection.")
            print()
            print("  Options:")
            print("  1. Connect a USB microphone to the Raspberry Pi")
            print("  2. Connect an I2S MEMS mic and enable it:")
            print("     Edit /boot/firmware/config.txt")
            print('     Uncomment: dtparam=i2s=on')
            print("=" * 55)
        else:
            print(f"VoiceActiveCrawler init failed: {err_msg}")

    def _init_crawler(self):
        try:
            self.crawler = Picrawler(speed_limit=self.move_speed_limit)
            time.sleep(1)
        except Exception as e:
            raise RuntimeError(f"Failed to initialize Picrawler: {e}")

    # ── lifecycle overrides ──────────────────────────────────────────

    def on_start(self):
        self._report_battery(startup=True)
        self._action_running = True
        self._action_thread = threading.Thread(
            target=self._action_handler, daemon=True
        )
        self._action_thread.start()
        self.crawler.do_action("sit", speed=50)
        if self.scheduler is not None:
            threading.Thread(target=self._scheduler_loop, daemon=True).start()
        self._idle.set()

    def before_listen(self):
        self.crawler.do_action("sit", speed=50)

    def on_wake(self):
        # wait out a running autonomous turn first (a few seconds at most), and go
        # busy under the same lock so no task can start in between
        with self._task_lock:
            self._idle.clear()
            self._conversation += 1
        self._interrupted = False
        if self.brain is not None:
            self._refresh_system_prompt()
            self.brain.start(self._system_msg["content"])
        self._report_battery()
        if self.greet_with_vision:
            self._vision_greeting()

    def before_think(self, text):
        self._refresh_system_prompt()
        if self._recording and text:
            self._transcript.append(("user", text))

    def after_think(self, text):
        if self._recording and text:
            self._transcript.append(("assistant", self._ACTIONS_RE.split(text, maxsplit=1)[0].strip()))

    def _refresh_system_prompt(self):
        # called from several threads now (conversation, prewarm, autonomous turns)
        with self._prompt_lock:
            msgs = self.llm.messages
            history = [m for m in msgs if m is not self._system_msg][-(self._history_limit - 1):]
            msgs[:] = [self._system_msg] + history
            # With the agent brain the date, time and battery come with every
            # message (turn_context, via its UserPromptSubmit hook), so the prompt
            # stays byte-stable across sessions for the prompt cache. The legacy
            # LLM has no hooks and keeps the section here.
            ahora = "" if self.brain is not None else self._ahora_section()
            self._system_msg["content"] = self.instructions + self.memory.prompt_section() + ahora

    def _ahora_line(self):
        now = datetime.datetime.now()
        dia = _WEEKDAYS_ES[now.weekday()]
        mes = _MONTHS_ES[now.month - 1]
        return f"Hoy es {dia} {now.day} de {mes} de {now.year}, {now.hour:02d}:{now.minute:02d}."

    def _ahora_section(self):
        return "\n## Ahora\n" + self._ahora_line() + "\n"

    def turn_context(self):
        """Per-turn context for the agent (its UserPromptSubmit hook): the date
        and time, plus the battery reading from the last check if there is one.
        No sensor is read here; this runs on every message."""
        text = self._ahora_line()
        v = self._last_volts
        if v is not None:
            text += f" Pila: {v:.2f} V" + (" (baja)." if v < self.battery_low_volts else ".")
        return text

    # Spanish (and a few loose English) names the LLM may emit -> ACTION_MAP keys
    ACTION_ALIASES = {
        "adelante": "forward", "avanzar": "forward", "avanza": "forward",
        "hacia adelante": "forward", "caminar": "forward", "camina": "forward",
        "atrás": "backward", "atras": "backward", "retroceder": "backward",
        "retrocede": "backward", "hacia atrás": "backward", "hacia atras": "backward",
        "girar a la izquierda": "turn left", "gira a la izquierda": "turn left",
        "izquierda": "turn left", "voltear a la izquierda": "turn left",
        "girar a la derecha": "turn right", "gira a la derecha": "turn right",
        "derecha": "turn right", "voltear a la derecha": "turn right",
        "sentarse": "sit", "siéntate": "sit", "sientate": "sit", "sentado": "sit",
        "pararse": "stand", "párate": "stand", "parate": "stand", "levantarse": "stand",
        "levántate": "stand", "levantate": "stand", "de pie": "stand", "ponerse de pie": "stand",
        "saludar": "wave", "saluda": "wave", "saludo": "wave",
        "lagartijas": "push up", "lagartija": "push up", "flexiones": "push up",
        "flexión": "push up", "hacer lagartijas": "push up", "push ups": "push up", "pushup": "push up",
        "perrear": "twerk", "perrea": "twerk", "perreo": "twerk", "twerkear": "twerk", "twerkea": "twerk",
        "twerking": "twerk", "modo fiesta": "twerk", "fiesta": "twerk", "reggaeton": "twerk",
        "reguetón": "twerk", "regueton": "twerk", "bailar reggaeton": "twerk", "bailar reguetón": "twerk",
        "trotar": "trot", "trota": "trot", "trote": "trot", "correr": "trot", "corre": "trot",
        "carrera": "trot", "run": "trot", "running": "trot", "jog": "trot",
        "mirar a la izquierda": "look left", "mira a la izquierda": "look left", "ver a la izquierda": "look left",
        "mirar a la derecha": "look right", "mira a la derecha": "look right", "ver a la derecha": "look right",
        "mirar arriba": "look up", "mira arriba": "look up", "mirar hacia arriba": "look up",
        "mirar abajo": "look down", "mira abajo": "look down", "mirar hacia abajo": "look down",
        "reverencia": "bow", "hacer una reverencia": "bow", "inclinarse": "bow", "caravana": "bow",
        "asentir": "nod", "asiente": "nod", "decir que sí": "nod", "decir que si": "nod",
        "negar": "shake head", "niega": "shake head", "decir que no": "shake head",
        "menear": "shimmy", "menearse": "shimmy", "menéate": "shimmy", "meneate": "shimmy",
        "bailar": "shimmy", "baila": "shimmy", "dance": "shimmy",
        "hula hula": "hula", "hula-hula": "hula", "círculos": "hula", "circulos": "hula",
        "brincar": "bounce", "brinca": "bounce", "saltar": "bounce", "salta": "bounce", "jump": "bounce",
        "girar": "spin", "gira": "spin", "dar una vuelta": "spin", "da una vuelta": "spin", "vuelta": "spin",
        "hacerse el muerto": "play dead", "hazte el muerto": "play dead", "muerto": "play dead",
        "chócala": "high five", "chocala": "high five", "choca esos cinco": "high five",
        "dame cinco": "high five", "high-five": "high five", "highfive": "high five",
        "parar": "stop", "detenerse": "stop", "detente": "stop", "alto": "stop", "quieto": "stop",
        "ninguna": "stop", "ninguno": "stop", "nada": "stop", "none": "stop",
    }

    def normalize_action(self, action):
        a = action.strip().strip('.;:"\'[]()').lower()
        if a in self.ACTION_MAP or a == "stop":
            return a
        m = self._FIND_RE.match(a)
        if m:
            return "find:" + m.group(1).strip()
        if a in self.ACTION_ALIASES:
            return self.ACTION_ALIASES[a]
        a2 = a.replace("_", " ")
        if a2 in self.ACTION_MAP:
            return a2
        return a

    def parse_response(self, text):
        if self._spoken_result is not None and text == self._spoken_result:
            # Streaming think() already spoke this and queued its actions.
            self._spoken_result = None
            return ""
        # Accept "ACTIONS:" or a translated "ACCIONES:" label, any case.
        result = re.split(r'\n?\s*(?:ACTIONS|ACCIONES|Acciones|Actions)\s*:\s*', text.strip(), maxsplit=1)

        response_text = result[0].strip()
        if len(result) > 1:
            actions_str = result[1].strip()
            if actions_str:
                actions = [self.normalize_action(a) for a in re.split(r'\s*[,;]\s*', actions_str) if a.strip()]
            else:
                actions = ['stop']
        else:
            actions = ['stop']

        if self.max_actions is not None:
            actions = actions[:self.max_actions] or ['stop']
        for action in actions:
            self.action_queue.put(action)

        return response_text

    def before_say(self, text):
        self._start_talking()

    def after_say(self, text):
        # round wrap-up (wait for actions, sit) happens in on_finish_a_round
        self._stop_talking()

    def _finish_round_motion(self):
        self._wait_actions_done()
        self._say_announcements()
        self.crawler.do_action("sit", speed=50)

    def on_stop(self):
        self._action_running = False
        # a conversation cut short by Ctrl-C: learn from it before exiting
        transcript, self._transcript = self._transcript, []
        self._log_conversation(transcript)
        self.memory.learn(transcript)
        self.crawler.do_action("sit", speed=50)

    # ── wake word (fuzzy) ─────────────────────────────────────────────

    @staticmethod
    def _norm_text(t):
        import unicodedata
        t = unicodedata.normalize("NFD", (t or "").lower())
        return " ".join("".join(c for c in t if unicodedata.category(c) != "Mn").split())

    def _fuzzy_heard_wake_word(self, print_callback=lambda x: print(f"heard: \x1b[K{x}", end="\r", flush=True)):
        result = self.stt.listen(stream=False)
        if result is None:
            return False
        print_callback(result)
        heard = self._norm_text(result)
        for w in (self.stt.wake_words or []):
            if self._wake_match(self._norm_text(w), heard):
                return True
        return False

    # What the small Spanish Vosk model tends to hear for each wake word.
    WAKE_ALIASES = {
        "compa": ("compa", "compra", "comprar", "compacta", "compadre", "con pa", "com"),
    }

    def _wake_match(self, wake, heard):
        for pat in (wake,) + tuple(self._norm_text(a) for a in self.WAKE_ALIASES.get(wake, ())):
            if len(pat) >= 5:
                if pat in heard:
                    return True
            elif re.search(r"\b" + re.escape(pat) + r"\b", heard):
                return True
        return False

    # ── streaming speech: talk while the LLM is still writing ────────

    _ACTIONS_RE = re.compile(r"\n?\s*(?:ACTIONS|ACCIONES|Acciones|Actions)\s*:")
    _HOLD_BACK = 12   # chars kept unspoken until we know they are not the start of "ACTIONS:"

    def think(self, text, disable_image=False):
        streaming = self.stream_speech and hasattr(self.tts, "instructions")
        if self.brain is None and not streaming:
            return super().think(text, disable_image=disable_image)
        self.before_think(text)
        if self.brain is not None:
            # the agent takes photos itself with the look tool
            self._tool_moves = 0
            if not streaming:
                return self._think_agent_once(text)
            return self._think_agent_streaming(text, disable_image)
        return self._think_llm_streaming(text, disable_image)

    def _think_agent_once(self, text):
        # non-streaming agent turn: no pipeline, so there is nothing to fall
        # back into mid-speech; just make sure a broken brain cannot raise.
        try:
            result = "".join(self.brain.ask(text, self._system_msg["content"])).strip()
        except Exception as e:
            if type(e).__name__ == "BudgetExceeded":
                result = self.budget_phrase
            else:
                print(f"(agente falló: {e})")
                result = self.brain_error_phrase
        self.after_think(result)
        return result

    def _llm_response(self, text, disable_image):
        """The legacy OpenAI streaming path: self.llm.prompt(..., stream=True)."""
        image_path = None
        if self.with_image and not disable_image:
            image_path = "./img_input.jpeg"
            self.capture_image(image_path)
        kwargs = {"image_path": image_path, "stream": True}
        if self.disable_think:
            kwargs["think"] = False
        return self.llm.prompt(text, **kwargs)

    def _stream_to_speech(self, response, pipeline, state=None):
        """Feed a text-chunk generator (LLM or agent reply) into the speech
        pipeline as it streams, holding back the ACTIONS:/ACCIONES: line so
        it is never spoken. Returns (llm_text, spoken_anything). If a dict is
        passed as ``state`` it is kept updated with the partial text and the
        spoken flag, so a caller that catches an exception raised while
        iterating ``response`` can still recover what happened so far."""
        if state is None:
            state = {}
        llm_text, spoken_upto, speaking, spoken_anything = "", 0, True, False
        for word in response:
            if not self.running:
                break
            if not word:
                continue
            print(word, end="", flush=True)
            llm_text += word
            state["text"] = llm_text
            if not speaking:
                continue
            m = self._ACTIONS_RE.search(llm_text)
            if m:
                chunk = llm_text[spoken_upto:m.start()]
                if chunk:
                    pipeline.feed(chunk)
                    spoken_anything = state["spoken"] = True
                speaking = False
            else:
                safe = len(llm_text) - self._HOLD_BACK
                if safe > spoken_upto:
                    pipeline.feed(llm_text[spoken_upto:safe])
                    spoken_anything = state["spoken"] = True
                    spoken_upto = safe
        print("")
        if speaking:
            chunk = llm_text[spoken_upto:]
            if chunk:
                pipeline.feed(chunk)
                spoken_anything = state["spoken"] = True
        return llm_text.strip(), spoken_anything

    def _think_llm_streaming(self, text, disable_image):
        from petronilo_voice import SpeechPipeline
        pipeline = SpeechPipeline(self.tts)
        self._pipeline = pipeline
        self._start_talking()
        try:
            response = self._llm_response(text, disable_image)
            result, _spoken = self._stream_to_speech(response, pipeline)
            self.after_think(result)
            # queue actions now so the body moves while he is still talking
            self._queue_actions(result)
            self._spoken_result = result
        finally:
            pipeline.finish()
            self._pipeline = None
            self._stop_talking()
        return result

    def _think_agent_streaming(self, text, disable_image):
        from petronilo_voice import SpeechPipeline
        pipeline = SpeechPipeline(self.tts)
        self._pipeline = pipeline
        self._start_talking()
        try:
            result = self._ask_agent_streaming(text, pipeline, disable_image)
            self.after_think(result)
            self._queue_actions(result)
            self._spoken_result = result
        finally:
            pipeline.finish()
            self._pipeline = None
            self._stop_talking()
        return result

    def _ask_agent_streaming(self, text, pipeline, disable_image):
        """Stream the agent's reply through pipeline; on failure, fall back
        to the legacy LLM if nothing was spoken yet, or speak an apology."""
        state = {}
        try:
            # a visual question (disable_image False, see _wants_image) takes a
            # frame along, so he answers from it instead of spending a look call
            image_path = None
            if self.with_image and not disable_image:
                image_path = "./img_input.jpeg"
                try:
                    self.capture_image(image_path)
                except Exception as e:
                    print(f"(sin foto: {e})")
                    image_path = None
            response = self.brain.ask(text, self._system_msg["content"], image_path=image_path)
            return self._stream_to_speech(response, pipeline, state)[0]
        except Exception as e:
            spoken = state.get("spoken", False)
            partial = state.get("text", "").strip()
            if type(e).__name__ == "BudgetExceeded":
                pipeline.feed(self.budget_phrase)
                return (partial + " " + self.budget_phrase).strip()
            if not spoken:
                print(f"(agente falló: {e}; contesto con el LLM de respaldo)")
                fallback_state = {}
                try:
                    response = self._llm_response(text, disable_image)
                    return self._stream_to_speech(response, pipeline, fallback_state)[0]
                except Exception as e2:
                    print(f"(respaldo LLM también falló: {e2})")
                    pipeline.feed(self.brain_error_phrase)
                    fb_partial = fallback_state.get("text", "").strip()
                    return (fb_partial + " " + self.brain_error_phrase).strip()
            print(f"(agente falló: {e})")
            pipeline.feed(self.brain_error_phrase)
            return (partial + " " + self.brain_error_phrase).strip()

    def _queue_actions(self, text):
        saved = self._spoken_result
        self._spoken_result = None
        try:
            VoiceActiveCrawler.parse_response(self, text)
        finally:
            self._spoken_result = saved

    # ── autonomous turns (reminders, control socket, Telegram) ───────

    def _acquire_idle(self, what):
        """Take _task_lock while he is idle, or give up after task_wait_seconds.
        Re-checks idle under the lock: a wake word may land between the wait
        and the acquire. The caller must release the lock."""
        deadline = time.time() + self.task_wait_seconds
        while True:
            remaining = deadline - time.time()
            if remaining <= 0 or not self._idle.wait(remaining):
                print(f"(tarea: seguía ocupado tras {self.task_wait_seconds}s, descarto: {what!r})")
                return False
            self._task_lock.acquire()
            if self._idle.is_set():
                return True
            self._task_lock.release()

    def run_task(self, prompt, speak=True):
        """One autonomous agent turn outside any wake-word conversation. Waits
        for an ongoing conversation to finish, then asks the brain (or the
        legacy LLM) and optionally speaks the reply. Returns the reply text
        ("" if it never got a turn in time)."""
        if not self._acquire_idle(prompt):
            return ""
        try:
            self._refresh_system_prompt()
            self._tool_moves = 0
            if self.brain is None:
                response = self._llm_response(prompt, True)
            else:
                response = self.brain.ask(prompt, self._system_msg["content"])
            if speak:
                from petronilo_voice import SpeechPipeline
                pipeline = SpeechPipeline(self.tts)
                self._pipeline = pipeline
                self._start_talking()
                state = {}
                try:
                    text = self._stream_to_speech(response, pipeline, state)[0]
                except Exception as e:
                    print(f"(tarea falló: {e})")
                    partial = state.get("text", "").strip()
                    if state.get("spoken", False):
                        text = partial
                    else:
                        pipeline.feed(self.brain_error_phrase)
                        text = (partial + " " + self.brain_error_phrase).strip()
                finally:
                    pipeline.finish()
                    self._pipeline = None
                    self._stop_talking()
                    self._wait_actions_done()
                    self.crawler.do_action("sit", speed=50)
            else:
                try:
                    text = "".join(response).strip()
                except Exception as e:
                    print(f"(tarea falló: {e})")
                    text = self.brain_error_phrase
            if self.brain is not None:
                # still under the lock: a wake word must not open its session
                # while this one is being closed
                self._finish_task_brain()
        finally:
            self._task_lock.release()
        print(f"(tarea: {text})")
        if speak and self.notify:
            try:
                self.notify(text)
            except Exception as e:
                print(f"(notificar falló: {e})")
        return text

    def _finish_task_brain(self):
        try:
            self.brain.end()
        except Exception as e:
            print(f"(agente: cierre falló: {e})")
        self._prewarm()

    def say(self, text):
        """Say text on his own, outside any conversation (e.g. a "say" reminder)."""
        if not text:
            return
        if not self._acquire_idle(text):
            return
        try:
            self.tts.say(text)
        finally:
            self._task_lock.release()
        if self.notify:
            try:
                self.notify(text)
            except Exception as e:
                print(f"(notificar falló: {e})")

    def stop_speaking(self):
        """Cancel whatever is being said and drain queued actions. Safe to
        call from any thread at any time."""
        if self._pipeline is not None:
            self._pipeline.cancel()
        while True:
            try:
                job = self.action_queue.get_nowait()
            except queue.Empty:
                break
            if isinstance(job, tuple) and job[0] == "call":
                job[4].set_exception(RuntimeError("cancelled"))
        self.action_queue.put("stop")

    def _scheduler_loop(self):
        while self._action_running:
            try:
                jobs = self.scheduler.pop_due()
            except Exception as e:
                print(f"(agenda falló: {e})")
                jobs = []
            for job in jobs:
                try:
                    print(f"(recordatorio: {self.scheduler.describe(job)})")
                    if job["kind"] == "say":
                        self.say(job["text"])
                    elif job["kind"] == "ask":
                        self.run_task(job["text"])
                except Exception as e:
                    print(f"(recordatorio falló: {e})")
            time.sleep(5)

    # ── memory ────────────────────────────────────────────────────────

    def _end_conversation(self):
        transcript, self._transcript = self._transcript, []
        conversation = self._conversation

        def finish():
            # one thread, in order: close the agent session, learn from the
            # transcript (memory_llm call), then reopen the session with the
            # freshly learned memory so the CLI start-up is off the critical
            # path of the next wake word. Each step is guarded so a failure
            # in one does not skip _idle.set() and wedge autonomous turns.
            if self.brain is not None:
                try:
                    self.brain.end()
                except Exception as e:
                    print(f"(agente: cierre falló: {e})")
            if transcript:
                self._log_conversation(transcript)
                try:
                    self.memory.learn(transcript)
                except Exception as e:
                    print(f"(memoria falló: {e})")
            self._prewarm()
            # not if a new conversation already started while this one was learning
            with self._task_lock:
                if self._conversation == conversation:
                    self._idle.set()

        threading.Thread(target=finish, daemon=True).start()

    def _log_conversation(self, transcript):
        """Keep the conversation word for word (memory/transcripts/), so recall
        can find what was actually said, not just the one-line daily note."""
        log = getattr(self.memory, "log_conversation", None)
        if not transcript or log is None:
            return
        try:
            log(transcript)
        except Exception as e:
            print(f"(memoria: no se pudo guardar la plática: {e})")

    def _prewarm(self):
        """Open the agent's next session ahead of time (no-op without a brain)."""
        if self.brain is None:
            return
        try:
            self._refresh_system_prompt()
            self.brain.start(self._system_msg["content"])
        except Exception as e:
            print(f"(agente: prewarm falló: {e})")

    # ── vision greeting on wake (opt-in) ─────────────────────────────

    def _vision_greeting(self):
        self._recording = False
        try:
            prompt = ("Te acaban de llamar. Mira la foto y saluda en UNA frase corta y chistosa a quien veas "
                      "o a lo que veas (si no ves a nadie, di algo gracioso al respecto). Sin línea ACTIONS.")
            greeting = self.think(prompt, disable_image=False)
            if greeting and self._spoken_result != greeting:
                self.tts.say(self.parse_response(greeting) or greeting)
            self._spoken_result = None
        except Exception as e:
            print(f"(saludo con cámara falló: {e})")
        finally:
            self._recording = True

    # ── battery ───────────────────────────────────────────────────────

    def battery_voltage(self):
        try:
            from robot_hat.device import get_battery_voltage
        except Exception:
            from robot_hat import get_battery_voltage
        try:
            return float(get_battery_voltage())
        except Exception:
            return None

    def _report_battery(self, startup=False):
        v = self.battery_voltage()
        if v is None:
            return
        self._last_volts = v
        if startup:
            print(f"Batería: {v:.2f} V")
        if v < self.battery_low_volts and time.time() - self._last_battery_warning > 600:
            self._last_battery_warning = time.time()
            print(f"(batería baja: {v:.2f} V)")
            if self.battery_warning:
                self.tts.say(self.battery_warning)

    # ── party (twerk.py) ──────────────────────────────────────────────

    def party(self, seconds=12):
        v = self.battery_voltage()
        if v is not None and v < self.battery_low_volts:
            print(f"(sin pila para perrear: {v:.2f} V)")
            return
        from twerk import party
        # the amp and all twelve servos share the HAT 5 V rail; loud music on top of
        # a fast twerk is the heaviest load on it (brownouts: docs/pi-config.md, finding 2)
        party(self.crawler, seconds=seconds, speed=55, volume=60)

    def trot(self, half_cycles=10):
        # every servo moves on every frame: same current draw worry as the twerk
        v = self.battery_voltage()
        if v is not None and v < self.battery_low_volts:
            print(f"(sin pila para trotar: {v:.2f} V)")
            return
        self.crawler.trot(half_cycles=half_cycles, stride=30, speed=80)

    # every servo moves on every frame (shimmy/hula reverse them too): same current draw worry as the twerk
    HEAVY_TRICKS = ("spin", "bounce", "shimmy", "hula")
    # actions the tool call should refuse up front on a low battery, before
    # answering "Doing it" (party/trot/trick already refuse quietly on their
    # own, but by then the agent has already told the person it would move)
    HEAVY_ACTIONS = {"twerk", "trot", *HEAVY_TRICKS}

    def trick(self, name):
        if name in self.HEAVY_TRICKS:
            v = self.battery_voltage()
            if v is not None and v < self.battery_low_volts:
                print(f"(sin pila para {name}: {v:.2f} V)")
                return
        self.crawler.trick(name)

    # ── find: look around for an object and walk up to it ──────────

    # "find red cup" / "buscar taza roja" / "encuentra mi taza" -> find:<target>
    _FIND_RE = re.compile(r"(?:search for|look for|find|search|buscar|busca|encontrar|encuentra)\s+(.+)")

    FIND_PHRASES = {
        "near": "¡Lo encontré, mijo! {target}, aquí enfrentito de mí.",
        "seen": "Ya vi {target}, pero no pude llegar hasta ahí.",
        "missing": "Chale, di toda la vuelta y no vi {target} por ningún lado.",
        "blind": "No puedo buscar {target}, mijo: traigo los ojos apagados.",
    }

    def find(self, target):
        self._announcements.append(self.seek(target))

    def seek(self, target):
        """Look for target and walk up to it; returns the phrase for the outcome."""
        # seek() walks the body, so it must not overlap with a queued move or
        # a fidget: route through the action thread when called from anywhere
        # else (the agent's find tool calls this from an asyncio worker thread)
        worker = self._action_thread
        if worker is not None and worker.is_alive() and threading.current_thread() is not worker:
            return self.run_on_action_thread(self.seek, target)
        from seeker import Seeker
        if not (self.with_image and self.locator):
            return self.find_phrases["blind"].format(target=target)
        frame = "./img_find.jpeg"

        def look():
            self.capture_image(frame)
            return frame

        seeker = Seeker(self.crawler, look, self.locator, self.sonar or (lambda: None))
        result = seeker.seek(target)
        print(f"(buscar {target!r}: {result})")
        kind = "missing" if not result.found else "near" if result.near else "seen"
        return self.find_phrases[kind].format(target=target)

    def _say_announcements(self):
        lines, self._announcements = self._announcements, []
        for line in lines:
            self.tts.say(line)
            # keep the outcome in the chat so "¿dónde estaba?" has an answer
            self.llm.messages.append({"role": "assistant", "content": line})
            if self._recording:
                self._transcript.append(("assistant", line))

    # ── camera: only send a frame when the question is visual ────────

    VISUAL_HINTS = ("ves", "ve ", "ver", "mira", "miras", "viendo", "foto", "camara", "imagen",
                    "que hay", "quien esta", "quien es", "quienes", "frente", "delante", "enfrente",
                    "color", "observa", "fijate", "describe", "cuantas personas", "cuantos", "que tengo",
                    "que traigo", "que llevo", "reconoces", "alrededor")

    # "mira a la izquierda" etc. are movement commands, not visual questions
    LOOK_COMMANDS = ("mira a la izquierda", "mira a la derecha", "mira hacia la izquierda",
                     "mira hacia la derecha", "mira arriba", "mira abajo", "mira hacia arriba",
                     "mira hacia abajo", "mira al frente", "ve a la izquierda", "ve a la derecha")

    def _wants_image(self, text):
        t = " " + self._norm_text(text) + " "
        for cmd in self.LOOK_COMMANDS:
            t = t.replace(cmd, " ")
        return any(h in t for h in self.VISUAL_HINTS)

    def trigger_wake_word(self):
        triggered, disable_image, message = super().trigger_wake_word()
        if triggered and message and not self._wants_image(message):
            disable_image = True
        return triggered, disable_image, message

    # ── robot tools for the agent brain (petronilo_agent.robot_tools) ─

    def queue_tool_action(self, action):
        """(message, is_error) for a move the agent asked for."""
        if action not in self.ACTION_MAP:
            return f"Unknown action {action!r}.", True
        if self.max_actions is not None and self._tool_moves >= self.max_actions:
            return f"Refused: at most {self.max_actions} move(s) per reply, to spare the battery.", True
        if action in self.HEAVY_ACTIONS:
            v = self.battery_voltage()
            if v is not None and v < self.battery_low_volts:
                return (f"Refused: battery at {v:.2f} V is too low for {action!r}; "
                        "say so and offer a gentler move."), True
        self._tool_moves += 1
        self.action_queue.put(action)
        return f"Doing {action!r} while you talk.", False

    def snapshot(self):
        if not self.with_image:
            return None
        path = "./img_input.jpeg"
        self.capture_image(path)
        return path

    def sensor_readings(self):
        distance = self.sonar() if self.sonar else None
        return {"battery_volts": self.battery_voltage(), "distance_cm": distance}

    # ── conversation mode (no wake word between turns) ───────────────

    def _is_end_phrase(self, text):
        t = self._norm_text(text)
        return any(p and p in t for p in self.end_phrases)

    def on_finish_a_round(self):
        try:
            self._follow_up()
        finally:
            self._end_conversation()

    def _follow_up(self):
        self._finish_round_motion()
        if not hasattr(self.stt, "follow_up_timeout"):
            return
        while self.running:
            # interrupted by the wake word: the question is coming, listen even
            # when conversation mode is off
            interrupted, self._interrupted = self._interrupted, False
            seconds = self.follow_up_seconds or (self.BARGE_IN_LISTEN_SECONDS if interrupted else 0)
            if not seconds:
                return
            if interrupted:
                print("(te escucho)")
            else:
                print(f"(sigo escuchando {seconds}s, sin palabra clave; di 'adiós' para terminar)")
            self.stt.follow_up_timeout = seconds
            try:
                text = self.listen()
            finally:
                self.stt.follow_up_timeout = None
            if not text:
                print("(silencio: vuelvo a esperar la palabra clave)")
                return
            if self._is_end_phrase(text):
                if self.farewell:
                    self.tts.say(self.farewell)
                return
            self.on_heard(text)
            result = self.think(text, disable_image=not self._wants_image(text))
            response_text = self.parse_response(result)
            if response_text:
                self.before_say(response_text)
                self.tts.say(response_text)
            self._finish_round_motion()

    # ── action dispatch ──────────────────────────────────────────────

    def run_on_action_thread(self, fn, *args, **kwargs):
        """Run fn(*args, **kwargs) on the action thread and block for its
        result. For calls that must not overlap a queued move or a fidget
        (e.g. seek(), which walks) but come from some other thread."""
        future = concurrent.futures.Future()
        self.action_queue.put(("call", fn, args, kwargs, future))
        return future.result()

    def _action_handler(self):
        while self._action_running:
            try:
                action = self.action_queue.get(timeout=0.5)
                self._action_busy.set()
                try:
                    if isinstance(action, tuple) and action[0] == "call":
                        _, fn, args, kwargs, future = action
                        try:
                            future.set_result(fn(*args, **kwargs))
                        except Exception as e:
                            future.set_exception(e)
                    elif action == 'stop':
                        self.crawler.do_action("sit", speed=50)
                    elif action.startswith("find:"):
                        self.find(action[5:])
                    elif action in self.ACTION_MAP:
                        method_name, kwargs = self.ACTION_MAP[action]
                        if method_name.startswith("self:"):
                            getattr(self, method_name[5:])(**kwargs)
                        else:
                            getattr(self.crawler, method_name)(**kwargs)
                    else:
                        print(f"Unknown action: {action}")
                except Exception as e:
                    print(f"(acción {action!r} falló: {e})")
                finally:
                    self._action_busy.clear()
            except queue.Empty:
                self._maybe_fidget()

    # ── fidgets: small gestures while talking ────────────────────────

    def _start_talking(self):
        if self.fidget_every:
            self._next_fidget = time.time() + random.uniform(*self.fidget_every) / 2
        self._talking.set()
        # only inside a conversation: during an autonomous turn the library's
        # wake-word thread already has the mic, and the wake word works as is
        if self._barge is not None and not self._idle.is_set():
            self._barge.start()

    def _stop_talking(self):
        self._talking.clear()
        if self._barge is not None:
            self._barge.stop()

    def _on_barge_in(self):
        """BargeIn heard the wake word mid-speech (runs on its thread): drop
        the rest of the answer and the queued moves, cut the brain's turn so
        the pending ask ends, and have _follow_up listen right away."""
        self._interrupted = True
        self.stop_speaking()
        brain = self.brain
        if brain is not None and callable(getattr(brain, "interrupt", None)):
            try:
                brain.interrupt()
            except Exception as e:
                print(f"(agente: no se pudo interrumpir: {e})")

    def _maybe_fidget(self):
        if not self.fidget_every or not self._talking.is_set() or time.time() < self._next_fidget:
            return
        self._next_fidget = time.time() + random.uniform(*self.fidget_every)
        v = self.battery_voltage()
        if v is not None and v < self.battery_low_volts:
            return
        self._action_busy.set()
        try:
            self.crawler.fidget()
        except Exception as e:
            print(f"(fidget falló: {e})")
        finally:
            self._action_busy.clear()

    def _wait_actions_done(self):
        # wait until the queue is empty AND the current action has finished
        while not self.action_queue.empty() or self._action_busy.is_set():
            time.sleep(0.05)
        time.sleep(0.1)
