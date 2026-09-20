import json
import os
import shutil
import socket
import sys
import tempfile
import threading
import unittest
import urllib.request
from datetime import datetime
from types import SimpleNamespace

sys.path.insert(0, os.path.join(os.path.dirname(os.path.realpath(__file__)), "..", "examples"))

import control  # noqa: E402
import petronilo_ctl  # noqa: E402
import telegram_bridge  # noqa: E402


class FakeScheduler:
    """In-memory stand-in for scheduler.Scheduler."""

    def __init__(self):
        self.jobs = []
        self._next_id = 1

    def add(self, when, text, kind="say", repeat=None):
        if when == "bad":
            raise ValueError(f"can't parse WHEN: {when!r}")
        job = {"id": self._next_id, "when": when, "text": text, "kind": kind,
               "repeat": repeat, "created": "2026-09-20T00:00:00"}
        self._next_id += 1
        self.jobs.append(job)
        return job

    def list(self):
        return list(self.jobs)

    def remove(self, job_id):
        for job in self.jobs:
            if job["id"] == job_id:
                self.jobs.remove(job)
                return True
        return False

    @staticmethod
    def describe(job):
        return f"{job['id']}: {job['text']}"


class FakeVA:
    def __init__(self):
        self.said = []
        self.asked = []
        self.stopped = False
        self.scheduler = FakeScheduler()
        self._idle = threading.Event()
        self._idle.set()
        self.brain = SimpleNamespace(spent_today=1.25)

    def say(self, text):
        self.said.append(text)

    def run_task(self, text, speak=True):
        self.asked.append((text, speak))
        return f"reply to {text}"

    def stop_speaking(self):
        self.stopped = True

    def battery_voltage(self):
        return 7.9


class ControlServerTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(dir="/private/tmp")
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.sock_path = os.path.join(self.tmp, "c.sock")
        self.va = FakeVA()
        self.server = control.ControlServer(self.va, path=self.sock_path)
        self.server.start()
        self.addCleanup(self.server.stop)

    def test_say(self):
        reply = control.request("say", self.sock_path, text="hola")
        self.assertTrue(reply["ok"], reply)
        self.assertEqual(reply["result"], "said")
        self.assertEqual(self.va.said, ["hola"])

    def test_ask_returns_text_and_passes_speak(self):
        reply = control.request("ask", self.sock_path, text="que hora es", speak=False)
        self.assertTrue(reply["ok"], reply)
        self.assertEqual(reply["result"], "reply to que hora es")
        self.assertEqual(self.va.asked, [("que hora es", False)])

    def test_ask_default_speak_is_true(self):
        control.request("ask", self.sock_path, text="hola")
        self.assertEqual(self.va.asked[-1], ("hola", True))

    def test_stop(self):
        reply = control.request("stop", self.sock_path)
        self.assertTrue(reply["ok"], reply)
        self.assertTrue(self.va.stopped)

    def test_remind_ok(self):
        reply = control.request("remind", self.sock_path, when="2026-01-01T08:00:00", text="feliz ano")
        self.assertTrue(reply["ok"], reply)
        self.assertIn("feliz ano", reply["result"])

    def test_remind_bad_when_is_error(self):
        reply = control.request("remind", self.sock_path, when="bad", text="x")
        self.assertFalse(reply["ok"])
        self.assertIn("error", reply)

    def test_jobs(self):
        control.request("remind", self.sock_path, when="2026-01-01T08:00:00", text="a")
        control.request("remind", self.sock_path, when="2026-01-02T08:00:00", text="b")
        reply = control.request("jobs", self.sock_path)
        self.assertTrue(reply["ok"], reply)
        self.assertEqual(len(reply["result"]), 2)

    def test_cancel_ok(self):
        control.request("remind", self.sock_path, when="2026-01-01T08:00:00", text="a")
        job_id = self.va.scheduler.jobs[0]["id"]
        reply = control.request("cancel", self.sock_path, id=job_id)
        self.assertTrue(reply["ok"], reply)
        self.assertEqual(reply["result"], "cancelled")
        self.assertEqual(self.va.scheduler.jobs, [])

    def test_cancel_missing(self):
        reply = control.request("cancel", self.sock_path, id=999)
        self.assertFalse(reply["ok"])

    def test_status(self):
        reply = control.request("status", self.sock_path)
        self.assertTrue(reply["ok"], reply)
        result = reply["result"]
        self.assertEqual(result["battery_volts"], 7.9)
        self.assertTrue(result["idle"])
        self.assertEqual(result["spent_today_usd"], 1.25)
        self.assertEqual(result["jobs"], [])

    def test_unknown_cmd(self):
        reply = control.request("frobnicate", self.sock_path)
        self.assertFalse(reply["ok"])

    def test_bad_json(self):
        sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        sock.connect(self.sock_path)
        sock.sendall(b"not json at all\n")
        chunks = []
        while True:
            chunk = sock.recv(4096)
            if not chunk:
                break
            chunks.append(chunk)
        sock.close()
        reply = json.loads(b"".join(chunks).decode("utf-8"))
        self.assertFalse(reply["ok"])
        self.assertIn("error", reply)


class ParseWhenTests(unittest.TestCase):
    def test_iso(self):
        self.assertEqual(petronilo_ctl.parse_when("2026-09-21T08:00:00"), "2026-09-21T08:00:00")

    def test_hhmm_today(self):
        now = datetime(2026, 9, 20, 8, 0, 0)
        self.assertEqual(petronilo_ctl.parse_when("09:00", now=now), "2026-09-20T09:00:00")

    def test_hhmm_tomorrow_when_already_past(self):
        now = datetime(2026, 9, 20, 8, 0, 0)
        self.assertEqual(petronilo_ctl.parse_when("07:00", now=now), "2026-09-21T07:00:00")

    def test_relative_minutes(self):
        now = datetime(2026, 9, 20, 8, 0, 0)
        self.assertEqual(petronilo_ctl.parse_when("+20m", now=now), "2026-09-20T08:20:00")

    def test_relative_hours(self):
        now = datetime(2026, 9, 20, 8, 0, 0)
        self.assertEqual(petronilo_ctl.parse_when("+2h", now=now), "2026-09-20T10:00:00")

    def test_relative_days(self):
        now = datetime(2026, 9, 20, 8, 0, 0)
        self.assertEqual(petronilo_ctl.parse_when("+1d", now=now), "2026-09-21T08:00:00")

    def test_bad_value_raises(self):
        with self.assertRaises(ValueError):
            petronilo_ctl.parse_when("not-a-time")


class TelegramBridgeTests(unittest.TestCase):
    def test_redact_strips_token_from_error_text(self):
        bridge = telegram_bridge.TelegramBridge("SECRETTOKEN", [1], FakeVA())
        error = Exception("failed at https://api.telegram.org/botSECRETTOKEN/getUpdates")
        redacted = bridge._redact(error)
        self.assertNotIn("SECRETTOKEN", redacted)
        self.assertIn("<token>", redacted)

    def test_send_with_no_chat_ids_never_calls_urlopen(self):
        bridge = telegram_bridge.TelegramBridge("TOKEN", [], FakeVA())
        called = []

        def fake_urlopen(*args, **kwargs):
            called.append((args, kwargs))
            raise AssertionError("urlopen should not be called with an empty allowlist")

        original = urllib.request.urlopen
        urllib.request.urlopen = fake_urlopen
        try:
            bridge.send("hola")
        finally:
            urllib.request.urlopen = original
        self.assertEqual(called, [])


if __name__ == "__main__":
    unittest.main()
