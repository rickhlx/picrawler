import os
import shutil
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.realpath(__file__)), "..", "examples"))

import memory  # noqa: E402


class MemoryToolTests(unittest.TestCase):
    def setUp(self):
        self.path = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.path, ignore_errors=True)
        self.mem = memory.Memory(self.path, llm=None)

    def _read(self, name):
        with open(os.path.join(self.path, name), encoding="utf-8") as f:
            return f.read()

    def test_add_fact_user_file(self):
        msg = self.mem.add_fact("A Ricardo le gusta el café", "user")
        self.assertIn("USER.md", msg)
        self.assertIn("A Ricardo le gusta el café", self._read("USER.md"))

    def test_add_fact_unknown_file_goes_to_memory(self):
        msg = self.mem.add_fact("Hay que regar las plantas", "bogus")
        self.assertIn("MEMORY.md", msg)
        self.assertIn("Hay que regar las plantas", self._read("MEMORY.md"))

    def test_add_fact_empty_is_ignored(self):
        msg = self.mem.add_fact("   ")
        self.assertEqual(msg, "Nothing to save.")
        self.assertEqual(self.mem.facts, [])

    def test_add_fact_dedup_case_and_accent_insensitive(self):
        self.mem.add_fact("A Ricardo le gusta el café", "user")
        msg = self.mem.add_fact("a ricardo le gusta el cafe", "user")
        self.assertEqual(msg, "Already known.")
        bullets = [l for l in self._read("USER.md").splitlines() if l.startswith("- ")]
        self.assertEqual(len(bullets), 1)
        self.assertEqual(len(self.mem.facts), 1)

    def test_add_fact_persists_across_reload(self):
        self.mem.add_fact("A Ricardo le gusta el café", "user")
        reloaded = memory.Memory(self.path, llm=None)
        self.assertEqual(len(reloaded.facts), 1)

    def test_remove_fact_by_substring(self):
        self.mem.add_fact("A Ricardo le gusta el café", "user")
        self.mem.add_fact("Hay que regar las plantas", "memory")
        n = self.mem.remove_fact("café")
        self.assertEqual(n, 1)
        self.assertEqual(len(self.mem.facts), 1)
        self.assertNotIn("café", self._read("USER.md"))

    def test_remove_fact_accent_insensitive(self):
        self.mem.add_fact("A Ricardo le gusta el café", "user")
        n = self.mem.remove_fact("CAFE")
        self.assertEqual(n, 1)

    def test_remove_fact_refuses_short_query(self):
        self.mem.add_fact("A Ricardo le gusta el café", "user")
        n = self.mem.remove_fact("ca")
        self.assertEqual(n, 0)
        self.assertEqual(len(self.mem.facts), 1)

    def test_remove_fact_no_match(self):
        self.mem.add_fact("A Ricardo le gusta el café", "user")
        n = self.mem.remove_fact("chocolate")
        self.assertEqual(n, 0)

    def test_search_matches_all_words_in_facts(self):
        self.mem.add_fact("A Ricardo le gusta el café negro", "user")
        self.mem.add_fact("Hay que regar las plantas", "memory")
        results = self.mem.search("ricardo cafe")
        self.assertEqual(len(results), 1)
        self.assertIn("café", results[0])
        self.assertTrue(results[0].startswith("USER.md:"))

    def test_search_requires_all_words(self):
        self.mem.add_fact("A Ricardo le gusta el café negro", "user")
        results = self.mem.search("ricardo chocolate")
        self.assertEqual(results, [])

    def test_search_daily_notes(self):
        self.mem._append_daily("Hablamos del clima", day="2026-09-19")
        results = self.mem.search("clima")
        self.assertEqual(len(results), 1)
        self.assertIn("2026-09-19", results[0])

    def test_search_notes_newest_first(self):
        self.mem._append_daily("Plática vieja sobre perros", day="2026-09-17")
        self.mem._append_daily("Plática nueva sobre perros", day="2026-09-19")
        results = self.mem.search("perros")
        self.assertEqual(len(results), 2)
        self.assertIn("2026-09-19", results[0])
        self.assertIn("2026-09-17", results[1])

    def test_search_respects_limit(self):
        for i in range(15):
            self.mem.add_fact(f"Dato numero {i} sobre gatos", "memory")
        results = self.mem.search("gatos", limit=5)
        self.assertEqual(len(results), 5)

    def test_prompt_section_includes_new_facts(self):
        self.mem.add_fact("A Ricardo le gusta el café", "user")
        section = self.mem.prompt_section()
        self.assertIn("café", section)

    def test_recent_returns_note_lines(self):
        self.mem._append_daily("Nota de hace unos días", day="2026-09-15")
        self.mem._append_daily("Nota de hoy", day="2026-09-20")
        notes = self.mem.recent(days=7)
        self.assertTrue(any("Nota de hoy" in n for n in notes))
        self.assertTrue(any("Nota de hace unos días" in n for n in notes))

    def test_recent_excludes_older_than_window(self):
        self.mem._append_daily("Muy vieja", day="2026-01-01")
        self.mem._append_daily("Reciente", day="2026-09-20")
        notes = self.mem.recent(days=1)
        self.assertTrue(any("Reciente" in n for n in notes))
        self.assertFalse(any("Muy vieja" in n for n in notes))

    def test_learn_still_works_unchanged(self):
        # learn() with no llm and no user turn should just no-op, not raise
        self.mem.learn([("assistant", "hola")])
        self.assertEqual(self.mem.facts, [])


if __name__ == "__main__":
    unittest.main()
