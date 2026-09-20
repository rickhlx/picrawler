"""Barge-in (examples/voice_active_crawler.py): the BargeIn listener and the
crawler methods around it, with fakes for the STT, the pipeline and the brain.
robot_hat is not installable here, so picrawler is stubbed just enough to
import the module; the crawler's methods are called unbound on a fake self."""
import os
import sys
import threading
import time
import types
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.realpath(__file__)), "..", "examples"))

if "picrawler" not in sys.modules:
    pkg = types.ModuleType("picrawler")
    pkg.Picrawler = type("Picrawler", (), {})
    va = types.ModuleType("picrawler.voice_assistant")
    va.VoiceAssistant = type("VoiceAssistant", (), {})
    pkg.voice_assistant = va
    sys.modules["picrawler"] = pkg
    sys.modules["picrawler.voice_assistant"] = va

import voice_active_crawler  # noqa: E402
from voice_active_crawler import BargeIn, VoiceActiveCrawler  # noqa: E402


class FakeRecognizer:
    def __init__(self):
        self.resets = 0

    def Reset(self):
        self.resets += 1


class FakeSTT:
    """listen(stream=False) hands out scripted transcripts; once the script is
    used up it blocks like Vosk waiting for speech, until stop_listening()."""

    def __init__(self, script):
        self.script = list(script)
        self.stop_listening_event = threading.Event()
        self.recognizer = FakeRecognizer()
        self.wake_word_thread = None
        self.calls = 0

    def listen(self, stream=False):
        self.stop_listening_event.clear()
        self.calls += 1
        if self.script:
            return self.script.pop(0)
        self.stop_listening_event.wait(5)
        return None

    def stop_listening(self):
        self.stop_listening_event.set()


def norm(t):
    import unicodedata
    t = unicodedata.normalize("NFD", (t or "").lower())
    return " ".join("".join(c for c in t if unicodedata.category(c) != "Mn").split())


class BargeInTests(unittest.TestCase):
    def _wait(self, cond, timeout=2.0):
        deadline = time.time() + timeout
        while not cond() and time.time() < deadline:
            time.sleep(0.01)
        return cond()

    def test_exact_wake_word_hits(self):
        hits = []
        stt = FakeSTT(["bla bla", "oye compa ya"])
        b = BargeIn(stt, ["compa"], lambda: hits.append(1), norm=norm)
        b.start()
        self.assertTrue(self._wait(lambda: hits))
        self.assertTrue(b.hit)
        self.assertTrue(self._wait(lambda: not b._thread.is_alive()))
        b.stop()

    def test_alias_does_not_hit(self):
        hits = []
        stt = FakeSTT(["compra pan", "com", "compadre", "con pa"])
        b = BargeIn(stt, ["compa"], lambda: hits.append(1), norm=norm)
        b.start()
        self.assertTrue(self._wait(lambda: stt.calls >= 5))   # script used up, now waiting
        self.assertEqual(hits, [])
        self.assertFalse(b.hit)
        b.stop()
        self.assertTrue(b._stop.is_set())

    def test_accent_and_case_insensitive(self):
        b = BargeIn(FakeSTT([]), ["compa"], lambda: None, norm=norm)
        self.assertTrue(b.matches("Oye, Compá"))
        self.assertTrue(b.matches("COMPA"))
        self.assertFalse(b.matches("compadre"))
        self.assertFalse(b.matches(""))
        self.assertFalse(b.matches(None))

    def test_stop_ends_thread_and_resets_recognizer(self):
        stt = FakeSTT([])
        b = BargeIn(stt, ["compa"], lambda: None, norm=norm)
        b.start()
        t = b._thread
        self.assertTrue(self._wait(lambda: stt.calls >= 1))
        b.stop(timeout=2.0)
        self.assertFalse(t.is_alive())
        self.assertIsNone(b._thread)
        self.assertEqual(stt.recognizer.resets, 1)
        self.assertTrue(stt.stop_listening_event.is_set())

    def test_stop_without_start_is_noop(self):
        stt = FakeSTT([])
        b = BargeIn(stt, ["compa"], lambda: None, norm=norm)
        b.stop()
        self.assertEqual(stt.recognizer.resets, 0)

    def test_start_twice_keeps_one_thread(self):
        stt = FakeSTT([])
        b = BargeIn(stt, ["compa"], lambda: None, norm=norm)
        b.start()
        t = b._thread
        b.start()
        self.assertIs(b._thread, t)
        b.stop()

    def test_mic_error_ends_quietly(self):
        class BrokenSTT(FakeSTT):
            def listen(self, stream=False):
                raise OSError("no input device")
        b = BargeIn(BrokenSTT([]), ["compa"], lambda: None, norm=norm)
        b.start()
        self.assertTrue(self._wait(lambda: not b._thread.is_alive()))
        self.assertFalse(b.hit)


class FakeBrain:
    def __init__(self):
        self.interrupts = 0

    def interrupt(self):
        self.interrupts += 1


class FakeSelf:
    """Just the attributes the crawler methods under test touch."""

    def __init__(self, barge=None, brain=None, idle=False):
        self.fidget_every = None
        self._talking = threading.Event()
        self._idle = threading.Event()
        if idle:
            self._idle.set()
        self._barge = barge
        self.brain = brain
        self._interrupted = False
        self.stopped = 0

    def stop_speaking(self):
        self.stopped += 1


class CrawlerHooksTests(unittest.TestCase):
    def test_on_barge_in_stops_speech_flags_and_interrupts_brain(self):
        brain = FakeBrain()
        me = FakeSelf(brain=brain)
        VoiceActiveCrawler._on_barge_in(me)
        self.assertTrue(me._interrupted)
        self.assertEqual(me.stopped, 1)
        self.assertEqual(brain.interrupts, 1)

    def test_on_barge_in_without_brain(self):
        me = FakeSelf(brain=None)
        VoiceActiveCrawler._on_barge_in(me)
        self.assertTrue(me._interrupted)
        self.assertEqual(me.stopped, 1)

    def test_start_talking_runs_listener_in_conversation_only(self):
        stt = FakeSTT([])
        barge = BargeIn(stt, ["compa"], lambda: None, norm=norm)
        me = FakeSelf(barge=barge, idle=False)
        VoiceActiveCrawler._start_talking(me)
        self.assertTrue(me._talking.is_set())
        self.assertIsNotNone(barge._thread)
        VoiceActiveCrawler._stop_talking(me)
        self.assertFalse(me._talking.is_set())
        self.assertIsNone(barge._thread)

    def test_start_talking_skips_listener_on_autonomous_turn(self):
        barge = BargeIn(FakeSTT([]), ["compa"], lambda: None, norm=norm)
        me = FakeSelf(barge=barge, idle=True)
        VoiceActiveCrawler._start_talking(me)
        self.assertIsNone(barge._thread)
        VoiceActiveCrawler._stop_talking(me)

    def test_disabled_is_noop(self):
        me = FakeSelf(barge=None)
        VoiceActiveCrawler._start_talking(me)
        self.assertTrue(me._talking.is_set())
        VoiceActiveCrawler._stop_talking(me)
        self.assertFalse(me._talking.is_set())

    def test_end_to_end_hit_through_crawler_callback(self):
        brain = FakeBrain()
        me = FakeSelf(brain=brain)
        stt = FakeSTT(["compa"])
        me._barge = BargeIn(stt, ["compa"], lambda: VoiceActiveCrawler._on_barge_in(me), norm=norm)
        VoiceActiveCrawler._start_talking(me)
        deadline = time.time() + 2
        while not me._interrupted and time.time() < deadline:
            time.sleep(0.01)
        self.assertTrue(me._interrupted)
        self.assertEqual(me.stopped, 1)
        self.assertEqual(brain.interrupts, 1)
        VoiceActiveCrawler._stop_talking(me)


if __name__ == "__main__":
    unittest.main()
