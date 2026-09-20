"""Local control socket for Petronilo: say/ask/stop/remind/jobs/cancel/status
from another process on the same Pi, without going through the wake word.

Protocol: connect, send one JSON object terminated by a newline, read one
JSON reply terminated by a newline, then the connection closes. Replies are
``{"ok": true, "result": ...}`` or ``{"ok": false, "error": "..."}``. Each
connection is handled on its own thread, since ``ask`` can run an agent turn
that takes up to a minute.

Used by petronilo_ctl.py (the CLI) and telegram_bridge.py (for /jobs and
/status); anything else running as root on the Pi can talk to it too, since
the socket is chmod 0o600.
"""
import json
import os
import socket
import threading

DEFAULT_SOCKET = "/run/petronilo.sock"


def job_list(va):
    """Human-readable lines for every scheduled job, or [] with no scheduler."""
    scheduler = getattr(va, "scheduler", None)
    if scheduler is None:
        return []
    return [scheduler.describe(job) for job in scheduler.list()]


def status_dict(va):
    """The fields reported by the ``status`` command (and Telegram's /status)."""
    brain = getattr(va, "brain", None)
    return {
        "battery_volts": va.battery_voltage(),
        "idle": va._idle.is_set(),
        "spent_today_usd": getattr(brain, "spent_today", None),
        "jobs": job_list(va),
    }


class ControlServer:
    """Accepts commands on a unix socket and runs them against a
    VoiceActiveCrawler (``va``)."""

    def __init__(self, va, path=DEFAULT_SOCKET):
        self.va = va
        self.path = path
        self._sock = None
        self._thread = None
        self._running = False

    def start(self):
        if os.path.exists(self.path):
            try:
                os.unlink(self.path)
            except OSError:
                pass
        self._sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self._sock.bind(self.path)
        os.chmod(self.path, 0o600)
        self._sock.listen(5)
        self._running = True
        self._thread = threading.Thread(target=self._accept_loop, daemon=True)
        self._thread.start()

    def stop(self):
        self._running = False
        if self._sock is not None:
            try:
                self._sock.close()
            except OSError:
                pass
        try:
            os.unlink(self.path)
        except OSError:
            pass

    def _accept_loop(self):
        while self._running:
            try:
                conn, _addr = self._sock.accept()
            except OSError:
                break   # socket closed by stop()
            try:
                threading.Thread(target=self._handle, args=(conn,), daemon=True).start()
            except Exception as e:
                print(f"(control: {e})")
                try:
                    conn.close()
                except OSError:
                    pass

    def _handle(self, conn):
        try:
            with conn.makefile("rb") as f:
                line = f.readline()
            try:
                req = json.loads(line.decode("utf-8"))
            except (ValueError, UnicodeDecodeError) as e:
                self._reply(conn, {"ok": False, "error": f"bad json: {e}"})
                return
            self._reply(conn, self._dispatch(req))
        except Exception as e:
            print(f"(control: {e})")
        finally:
            try:
                conn.close()
            except OSError:
                pass

    def _reply(self, conn, obj):
        try:
            conn.sendall((json.dumps(obj) + "\n").encode("utf-8"))
        except OSError:
            pass

    def _dispatch(self, req):
        if not isinstance(req, dict):
            return {"ok": False, "error": "request must be a json object"}
        cmd = req.get("cmd")
        try:
            if cmd == "say":
                self.va.say(req["text"])
                return {"ok": True, "result": "said"}
            if cmd == "ask":
                result = self.va.run_task(req["text"], req.get("speak", True))
                return {"ok": True, "result": result}
            if cmd == "stop":
                self.va.stop_speaking()
                return {"ok": True, "result": "stopped"}
            if cmd == "remind":
                return self._remind(req)
            if cmd == "jobs":
                return {"ok": True, "result": job_list(self.va)}
            if cmd == "cancel":
                return self._cancel(req)
            if cmd == "status":
                return {"ok": True, "result": status_dict(self.va)}
            return {"ok": False, "error": f"unknown cmd {cmd!r}"}
        except KeyError as e:
            return {"ok": False, "error": f"missing field {e}"}
        except Exception as e:
            return {"ok": False, "error": str(e)}

    def _remind(self, req):
        scheduler = self.va.scheduler
        if scheduler is None:
            return {"ok": False, "error": "no scheduler configured"}
        try:
            job = scheduler.add(
                req["when"], req["text"],
                kind=req.get("kind", "say"),
                repeat=req.get("repeat"),
            )
        except ValueError as e:
            return {"ok": False, "error": str(e)}
        return {"ok": True, "result": scheduler.describe(job)}

    def _cancel(self, req):
        scheduler = self.va.scheduler
        if scheduler is None:
            return {"ok": False, "error": "no scheduler configured"}
        if scheduler.remove(req["id"]):
            return {"ok": True, "result": "cancelled"}
        return {"ok": False, "error": f"no job {req.get('id')!r}"}


def request(cmd, path=DEFAULT_SOCKET, timeout=900, **fields):
    """Send one command to a running ControlServer and return its reply dict.
    Raises OSError (e.g. FileNotFoundError, ConnectionRefusedError) if the
    socket isn't there or nobody is listening."""
    payload = {"cmd": cmd, **fields}
    sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    sock.settimeout(timeout)
    try:
        sock.connect(path)
        sock.sendall((json.dumps(payload) + "\n").encode("utf-8"))
        # no shutdown(SHUT_WR) here: the request is newline-delimited, so the
        # server's readline() does not need EOF to know it has the whole
        # thing, and a fast reply can otherwise race a local shutdown()
        # into ENOTCONN once the server has already closed its end.
        chunks = []
        while True:
            chunk = sock.recv(4096)
            if not chunk:
                break
            chunks.append(chunk)
        data = b"".join(chunks).decode("utf-8").strip()
        return json.loads(data)
    finally:
        sock.close()
