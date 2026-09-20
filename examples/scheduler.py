"""Persistent reminders and tasks for the voice assistant's agent brain.

One JSON file holds every job: a "say" (the robot speaks `text` verbatim
when due) or an "ask" (the agent runs `text` as a prompt when due, e.g.
"revisa el clima y avisale a Ricardo"). `Scheduler.pop_due` is polled by the
voice loop; a repeating job is re-armed instead of removed.

Job dict: {"id": <6-char hex>, "when": "<ISO seconds>", "text": ...,
"kind": "say" | "ask", "repeat": None | "daily" | "weekly", "created": "<ISO>"}
"""
import json
import threading
import uuid
from datetime import datetime, timedelta

from memory import _write

KINDS = ("say", "ask")
REPEATS = (None, "daily", "weekly")
_STEP = {"daily": timedelta(days=1), "weekly": timedelta(days=7)}


class Scheduler:
    def __init__(self, path):
        self.path = path
        self._lock = threading.Lock()
        self.jobs = self._load()

    def _load(self):
        try:
            with open(self.path, encoding="utf-8") as f:
                data = json.load(f)
        except FileNotFoundError:
            return []
        except Exception as e:
            print(f"(scheduler: no se pudo leer {self.path}: {e})")
            return []
        return data if isinstance(data, list) else []

    def _save(self):
        _write(self.path, json.dumps(self.jobs, ensure_ascii=False, indent=2))

    def add(self, when, text, kind="say", repeat=None):
        text = (text or "").strip()
        if not text:
            raise ValueError("text is required")
        if kind not in KINDS:
            raise ValueError(f"kind must be one of {KINDS}")
        if repeat not in REPEATS:
            raise ValueError(f"repeat must be one of {REPEATS}")
        dt = _parse_when(when)
        job = {
            "id": uuid.uuid4().hex[:6],
            "when": dt.isoformat(timespec="seconds"),
            "text": text,
            "kind": kind,
            "repeat": repeat,
            "created": datetime.now().isoformat(timespec="seconds"),
        }
        with self._lock:
            self.jobs.append(job)
            self._save()
        return job

    def list(self):
        with self._lock:
            return sorted(self.jobs, key=lambda j: j["when"])

    def remove(self, job_id):
        with self._lock:
            before = len(self.jobs)
            self.jobs = [j for j in self.jobs if j["id"] != job_id]
            changed = len(self.jobs) != before
            if changed:
                self._save()
        return changed

    def pop_due(self, now=None):
        """Jobs whose time has come, removed from the file (or re-armed, for
        a repeating job). Returns them sorted by when they were due."""
        now = now or datetime.now()
        due = []
        with self._lock:
            keep = []
            for job in self.jobs:
                when = datetime.fromisoformat(job["when"])
                if when > now:
                    keep.append(job)
                    continue
                due.append(job)
                step = _STEP.get(job.get("repeat"))
                if step:
                    while when <= now:
                        when += step
                    keep.append(dict(job, when=when.isoformat(timespec="seconds")))
            if due:
                self.jobs = keep
                self._save()
        due.sort(key=lambda j: j["when"])
        return due

    @staticmethod
    def describe(job):
        when = datetime.fromisoformat(job["when"])
        today = datetime.now().date()
        if when.date() == today:
            day = "hoy"
        elif when.date() == today + timedelta(days=1):
            day = "mañana"
        else:
            day = f"{when:%d %b}"
        repeat = {"daily": "cada día", "weekly": "cada semana"}.get(job.get("repeat"))
        when_str = f"{day} {when:%H:%M}" + (f", {repeat}" if repeat else "")
        return f"{job['id']}: {when_str}: {job['text']}"


def _parse_when(when):
    if isinstance(when, datetime):
        dt = when
    elif isinstance(when, str):
        s = when.strip()
        if not s:
            raise ValueError("when is required")
        if s.endswith("Z"):
            s = s[:-1]
        try:
            dt = datetime.fromisoformat(s)
        except ValueError:
            raise ValueError(f"unparsable date/time: {when!r}")
    else:
        raise ValueError(f"unparsable date/time: {when!r}")
    if dt.tzinfo is not None:
        dt = dt.astimezone().replace(tzinfo=None)
    return dt
