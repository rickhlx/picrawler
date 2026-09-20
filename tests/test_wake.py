"""Wake-word matching (examples/wake.py): does "compa" count when it lands in
the middle of a sentence, and is there a question around it worth answering?"""
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.realpath(__file__)), "..", "examples"))

import wake  # noqa: E402


WAKE = ["compa"]


class MatchTests(unittest.TestCase):
    def test_on_its_own(self):
        self.assertTrue(wake.matches("compa", WAKE))

    def test_anywhere_in_a_sentence(self):
        for heard in ("oye compa ven acá",
                      "¿qué onda, compa?",
                      "a ver, compa, ¿qué hora es?",
                      "ya me voy compa"):
            self.assertTrue(wake.matches(heard, WAKE), heard)

    def test_accent_and_case_insensitive(self):
        self.assertTrue(wake.matches("Óyeme COMPA, ¿cómo estás?", WAKE))

    def test_vosk_near_misses(self):
        for heard in ("compra", "compadre", "oye compacta ven", "con pa qué onda"):
            self.assertTrue(wake.matches(heard, WAKE), heard)

    def test_absent(self):
        for heard in ("qué hora es", "ponme música", "", None):
            self.assertFalse(wake.matches(heard, WAKE), heard)

    def test_short_alias_needs_word_boundaries(self):
        # "com" is an alias, but not inside another word
        self.assertTrue(wake.matches("com ven", WAKE))
        self.assertFalse(wake.matches("vamos a comer", WAKE))

    def test_no_wake_words_configured(self):
        self.assertFalse(wake.matches("compa", []))
        self.assertFalse(wake.matches("compa", None))


class RemainderTests(unittest.TestCase):
    def test_drops_the_wake_word_and_vocatives(self):
        self.assertEqual(wake.remainder("oye compa, ¿qué hora es?", WAKE), "que hora es")

    def test_words_on_both_sides(self):
        self.assertEqual(wake.remainder("a ver compa ven acá", WAKE), "a ver ven aca")

    def test_nothing_but_the_wake_word(self):
        self.assertEqual(wake.remainder("¡compa!", WAKE), "")
        self.assertEqual(wake.remainder("oye, compa", WAKE), "")

    def test_no_wake_word(self):
        self.assertEqual(wake.remainder("qué hora es", WAKE), "")


class QuestionTests(unittest.TestCase):
    def test_question_in_the_same_breath(self):
        for heard in ("compa, ¿qué hora es?",
                      "oye compa ven acá rápido",
                      "¿compa, cómo se llama mi perro?",
                      "compa cuéntame un chiste"):
            self.assertTrue(wake.has_question(heard, WAKE), heard)

    def test_just_the_wake_word(self):
        for heard in ("compa", "oye compa", "¡compa!", "hey compa", "compa ven"):
            self.assertFalse(wake.has_question(heard, WAKE), heard)

    def test_stray_syllable_is_not_a_question(self):
        # what the Vosk model tacks onto a bare wake word
        for heard in ("compa a", "eh compa eh", "compra el"):
            self.assertFalse(wake.has_question(heard, WAKE), heard)


class QuestionInWakeTests(unittest.TestCase):
    """What trigger_wake_word gets: the cloud reading of the wake utterance when
    it carried a question, None when it should just ask."""

    PCM = b"\x00\x01" * 100

    def cloud(self, text):
        calls = []

        def transcribe(pcm):
            calls.append(pcm)
            return text

        return transcribe, calls

    def test_cloud_reading_of_the_whole_sentence(self):
        transcribe, calls = self.cloud("Oye compa, ¿qué hora es?")
        self.assertEqual(wake.question_in("oye compra que ora es", WAKE, self.PCM, transcribe),
                         "Oye compa, ¿qué hora es?")
        self.assertEqual(calls, [self.PCM])

    def test_bare_wake_word_never_reaches_the_cloud(self):
        transcribe, calls = self.cloud("Compa")
        self.assertIsNone(wake.question_in("oye compa", WAKE, self.PCM, transcribe))
        self.assertEqual(calls, [])

    def test_cloud_hears_only_the_wake_word(self):
        transcribe, _ = self.cloud("Compa.")
        self.assertIsNone(wake.question_in("compa ven aca rapido", WAKE, self.PCM, transcribe))

    def test_cloud_failure_falls_back_to_asking(self):
        transcribe, _ = self.cloud(None)
        self.assertIsNone(wake.question_in("compa que hora es", WAKE, self.PCM, transcribe))

    def test_without_audio_or_transcriber(self):
        transcribe, _ = self.cloud("compa, ¿qué hora es?")
        self.assertIsNone(wake.question_in("compa que hora es", WAKE, None, transcribe))
        self.assertIsNone(wake.question_in("compa que hora es", WAKE, self.PCM, None))


if __name__ == "__main__":
    unittest.main()
