import os
import shutil
import sys
import tempfile
import unittest
from datetime import datetime

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

    # ── verbatim transcripts ─────────────────────────────────────────

    def _log(self, turns, when="2026-09-20 18:05"):
        self.mem.log_conversation(turns, when=datetime.strptime(when, "%Y-%m-%d %H:%M"))

    def test_log_conversation_writes_heading_and_both_labels(self):
        self._log([("user", "Acuérdate que el dentista es el jueves"), ("assistant", "Órale, apuntado.")])
        text = self._read(os.path.join("transcripts", "2026-09-20.md"))
        self.assertIn("# 2026-09-20", text)
        self.assertIn("## 18:05", text)
        self.assertIn("- Usuario: Acuérdate que el dentista es el jueves", text)
        self.assertIn("- the robot: Órale, apuntado.", text)

    def test_log_conversation_uses_robot_name_and_flattens_newlines(self):
        mem = memory.Memory(self.path, llm=None, name="Petronilo")
        mem.log_conversation([("user", "hola\n¿qué haces?"), ("assistant", "nada,\naquí nomás")],
                             when=datetime(2026, 9, 20, 9, 0))
        text = self._read(os.path.join("transcripts", "2026-09-20.md"))
        self.assertIn("- Usuario: hola ¿qué haces?\n", text)
        self.assertIn("- Petronilo: nada, aquí nomás\n", text)

    def test_log_conversation_same_day_appends_second_block(self):
        self._log([("user", "primera plática"), ("assistant", "sí")], when="2026-09-20 10:00")
        self._log([("user", "segunda plática"), ("assistant", "también")], when="2026-09-20 11:30")
        text = self._read(os.path.join("transcripts", "2026-09-20.md"))
        self.assertEqual(text.count("# 2026-09-20\n"), 1)
        self.assertIn("## 10:00", text)
        self.assertIn("## 11:30", text)
        self.assertLess(text.index("primera"), text.index("segunda"))

    def test_log_conversation_skips_empty_and_assistant_only(self):
        self.mem.log_conversation([])
        self.mem.log_conversation([("assistant", "hola"), ("user", "   ")])
        self.assertFalse(os.path.exists(os.path.join(self.path, "transcripts")))

    def test_search_finds_transcript_line_with_date_and_time(self):
        self._log([("user", "El dentista es el jueves a las cuatro"), ("assistant", "va")])
        results = self.mem.search("dentista jueves")
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0], "2026-09-20 18:05 Usuario: El dentista es el jueves a las cuatro")

    def test_search_puts_facts_and_notes_before_transcripts(self):
        self._log([("user", "Hablamos de gatos"), ("assistant", "miau")])
        self.mem._append_daily("Plática sobre gatos", day="2026-09-19")
        self.mem.add_fact("A Sofía le gustan los gatos", "user")
        results = self.mem.search("gatos")
        self.assertEqual(len(results), 3)
        self.assertTrue(results[0].startswith("USER.md:"))
        self.assertTrue(results[1].startswith("2026-09-19 "))
        self.assertIn("Usuario: Hablamos de gatos", results[2])

    def test_search_transcripts_newest_first(self):
        self._log([("user", "perros viejos"), ("assistant", "ok")], when="2026-09-18 08:00")
        self._log([("user", "perros de la mañana"), ("assistant", "ok")], when="2026-09-20 08:00")
        self._log([("user", "perros de la tarde"), ("assistant", "ok")], when="2026-09-20 17:00")
        results = self.mem.search("perros")
        self.assertEqual([r.split(" Usuario: ")[1] for r in results],
                         ["perros de la tarde", "perros de la mañana", "perros viejos"])

    def test_search_limit_applies_across_sources(self):
        for i in range(4):
            self.mem.add_fact(f"Dato {i} sobre loros", "memory")
        self._log([("user", "loros en la plática"), ("assistant", "loros, sí")])
        results = self.mem.search("loros", limit=5)
        self.assertEqual(len(results), 5)
        self.assertEqual(sum(r.startswith("MEMORY.md:") for r in results), 4)
        self.assertEqual(sum("Usuario:" in r or "the robot:" in r for r in results), 1)

    def test_prune_removes_old_transcripts_keeps_recent(self):
        mem = memory.Memory(self.path, llm=None, transcript_days=30)
        mem.log_conversation([("user", "muy viejo"), ("assistant", "ok")], when=datetime(2026, 6, 1, 9, 0))
        mem.log_conversation([("user", "reciente"), ("assistant", "ok")], when=datetime(2026, 9, 10, 9, 0))
        mem.log_conversation([("user", "hoy"), ("assistant", "ok")], when=datetime(2026, 9, 20, 9, 0))
        names = sorted(os.listdir(os.path.join(self.path, "transcripts")))
        self.assertEqual(names, ["2026-09-10.md", "2026-09-20.md"])

    def test_prompt_section_excludes_transcripts(self):
        self._log([("user", "palabra secreta xilófono"), ("assistant", "ok")])
        self.mem.add_fact("Un dato cualquiera", "memory")
        self.assertNotIn("xilófono", self.mem.prompt_section())
        self.assertNotIn("Usuario:", self.mem.prompt_section())

    def test_learn_with_extract_json_object(self):
        class FakeExtractor:
            def __init__(self):
                self.calls = []

            def extract_json(self, system, user):
                self.calls.append((system, user))
                return {"add": [{"file": "user", "text": "Ricardo cumple el 3 de mayo"}],
                        "update": [], "delete": [], "summary": "Hablaron del cumpleaños de Ricardo"}

        ext = FakeExtractor()
        mem = memory.Memory(self.path, llm=ext, name="Petronilo")
        mem.learn([("user", "mi cumple es el 3 de mayo"), ("assistant", "apuntado")])
        self.assertEqual(len(ext.calls), 1)
        system, user = ext.calls[0]
        self.assertIn("Petronilo", system)
        self.assertIn("mi cumple es el 3 de mayo", user)
        self.assertIn("Ricardo cumple el 3 de mayo", self._read("USER.md"))
        self.assertIn("Hablaron del cumpleaños de Ricardo", mem.prompt_section())

    def test_learn_with_extract_json_rejects_non_object(self):
        class Bad:
            def extract_json(self, system, user):
                return ["not", "a", "dict"]

        mem = memory.Memory(self.path, llm=Bad())
        mem.learn([("user", "hola")])   # logged, not raised
        self.assertEqual(mem.facts, [])

    def test_learn_still_works_unchanged(self):
        # learn() with no llm and no user turn should just no-op, not raise
        self.mem.learn([("assistant", "hola")])
        self.assertEqual(self.mem.facts, [])


if __name__ == "__main__":
    unittest.main()
