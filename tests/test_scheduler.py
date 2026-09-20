import json
import os
import shutil
import sys
import tempfile
import unittest
from datetime import datetime, timedelta

sys.path.insert(0, os.path.join(os.path.dirname(os.path.realpath(__file__)), "..", "examples"))

import scheduler  # noqa: E402


class SchedulerTests(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.dir, ignore_errors=True)
        self.path = os.path.join(self.dir, "jobs.json")
        self.sched = scheduler.Scheduler(self.path)

    def test_add_returns_job_with_short_id(self):
        job = self.sched.add("2026-09-21T08:00", "Recordar la cita del dentista")
        self.assertEqual(len(job["id"]), 6)
        self.assertEqual(job["kind"], "say")
        self.assertIsNone(job["repeat"])
        self.assertEqual(job["when"], "2026-09-21T08:00:00")

    def test_add_and_list(self):
        self.sched.add("2026-09-22T08:00", "segunda")
        self.sched.add("2026-09-21T08:00", "primera")
        jobs = self.sched.list()
        self.assertEqual([j["text"] for j in jobs], ["primera", "segunda"])

    def test_add_accepts_datetime(self):
        when = datetime(2026, 9, 22, 9, 30)
        job = self.sched.add(when, "tarea", kind="ask")
        self.assertEqual(job["when"], "2026-09-22T09:30:00")

    def test_add_accepts_trailing_z(self):
        job = self.sched.add("2026-09-21T08:00:00Z", "text")
        self.assertEqual(job["when"], "2026-09-21T08:00:00")

    def test_add_empty_text_raises(self):
        with self.assertRaises(ValueError):
            self.sched.add("2026-09-21T08:00", "")

    def test_add_empty_when_raises(self):
        with self.assertRaises(ValueError):
            self.sched.add("", "text")

    def test_add_unparsable_when_raises(self):
        with self.assertRaises(ValueError):
            self.sched.add("not-a-date", "text")

    def test_add_bad_kind_raises(self):
        with self.assertRaises(ValueError):
            self.sched.add("2026-09-21T08:00", "text", kind="shout")

    def test_add_bad_repeat_raises(self):
        with self.assertRaises(ValueError):
            self.sched.add("2026-09-21T08:00", "text", repeat="monthly")

    def test_remove_existing(self):
        job = self.sched.add("2026-09-21T08:00", "text")
        self.assertTrue(self.sched.remove(job["id"]))
        self.assertEqual(self.sched.list(), [])

    def test_remove_missing_returns_false(self):
        self.assertFalse(self.sched.remove("abcdef"))

    def test_pop_due_only_returns_due_jobs(self):
        past = datetime.now() - timedelta(minutes=5)
        future = datetime.now() + timedelta(days=1)
        self.sched.add(past, "due now")
        self.sched.add(future, "not yet")
        due = self.sched.pop_due()
        self.assertEqual([j["text"] for j in due], ["due now"])
        remaining = self.sched.list()
        self.assertEqual([j["text"] for j in remaining], ["not yet"])

    def test_pop_due_removes_non_repeating_job(self):
        past = datetime.now() - timedelta(minutes=1)
        self.sched.add(past, "once")
        self.sched.pop_due()
        self.assertEqual(self.sched.list(), [])

    def test_pop_due_rearms_daily_repeat_into_future(self):
        past = datetime.now() - timedelta(days=1, minutes=1)
        self.sched.add(past, "daily thing", repeat="daily")
        due = self.sched.pop_due()
        self.assertEqual(len(due), 1)
        remaining = self.sched.list()
        self.assertEqual(len(remaining), 1)
        new_when = datetime.fromisoformat(remaining[0]["when"])
        self.assertGreater(new_when, datetime.now())

    def test_pop_due_rearms_weekly_repeat_multiple_periods_missed(self):
        past = datetime.now() - timedelta(days=20)
        self.sched.add(past, "weekly thing", repeat="weekly")
        due = self.sched.pop_due()
        self.assertEqual(len(due), 1)
        remaining = self.sched.list()
        new_when = datetime.fromisoformat(remaining[0]["when"])
        self.assertGreater(new_when, datetime.now())

    def test_persistence_across_instances(self):
        self.sched.add("2026-09-21T08:00", "text")
        second = scheduler.Scheduler(self.path)
        self.assertEqual(len(second.list()), 1)
        self.assertEqual(second.list()[0]["text"], "text")

    def test_corrupt_file_becomes_empty_list(self):
        with open(self.path, "w", encoding="utf-8") as f:
            f.write("not json{{{")
        sched = scheduler.Scheduler(self.path)
        self.assertEqual(sched.list(), [])

    def test_missing_file_becomes_empty_list(self):
        sched = scheduler.Scheduler(os.path.join(self.dir, "does_not_exist.json"))
        self.assertEqual(sched.list(), [])

    def test_describe_contains_id_and_is_nonempty(self):
        job = self.sched.add("2026-09-21T08:00", "Recordar la cita del dentista")
        desc = scheduler.Scheduler.describe(job)
        self.assertTrue(desc)
        self.assertIn(job["id"], desc)
        self.assertIn("Recordar la cita del dentista", desc)

    def test_file_is_valid_json_on_disk(self):
        self.sched.add("2026-09-21T08:00", "text")
        with open(self.path, encoding="utf-8") as f:
            data = json.load(f)
        self.assertEqual(len(data), 1)


if __name__ == "__main__":
    unittest.main()
