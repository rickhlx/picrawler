"""Long-term memory for the voice assistant, learned automatically.

Stored as Markdown in a workspace folder, laid out the way OpenClaw keeps its
agent memory:

    petronilo_memory/
      USER.md               who the family are: names, relationships, birthdays, likes
      MEMORY.md             everything else worth keeping: plans, running jokes, requests
      memory/
        2026-09-18.md       daily notes, one line per conversation

When a conversation ends, `Memory.learn(transcript)` sends the transcript and
the stored facts to an LLM, which answers with edits (add / update / delete,
each fact in USER.md or MEMORY.md) and a one-line summary appended to today's
note. `prompt_section()` renders USER.md, MEMORY.md and the two most recent
daily notes for the system prompt.

Facts are the "- " bullets of USER.md and MEMORY.md. The files can be edited
by hand (with the assistant stopped): text above the first bullet is kept.
"""
import json
import os
import threading
from datetime import date, datetime

EXTRACT_PROMPT = """You maintain the long-term memory of {name}, a voice assistant robot that lives with a family.
Today is {today}. Read the conversation and update the memory.

Keep facts that will still matter in future conversations. Memory has two files:
- "user": USER.md, the people (and pets) {name} talks to: who they are, names, relationships, ages,
  birthdays, what they like and dislike, how they like to be treated.
- "memory": MEMORY.md, everything else durable: plans and dates, running jokes, things someone asked to
  be remembered, decisions, facts about the house.
Skip small talk, the robot's own jokes and trivia, things that only matter right now, and secrets such as
passwords or card numbers. The user side is speech-to-text and can be garbled: do not store a name or
detail you are unsure was heard correctly.

Write each fact as one short standalone sentence in the language of the conversation, saying who it is
about, with relative dates turned into absolute ones ("mañana" -> the actual date). If something is a secret
or a surprise, say in the fact who must not find out. Update a fact when the conversation changes or
corrects it (and move it to the other file if it is in the wrong one), delete it when it turned out wrong
or someone asks to forget it, and never add a duplicate. Memory holds at most {max_facts} facts and has
{count} now; when it is close to full, merge related facts and drop the least useful ones.

Reply with JSON only, in this shape (empty lists when nothing changes):
{{"add": [{{"file": "user", "text": "fact"}}], "update": [{{"id": 3, "text": "fact", "file": "memory"}}],
"delete": [5], "summary": "..."}}
"file" in an update is optional (omit it to keep the fact where it is).
"summary" is one sentence on what the conversation was about, or "" for small talk and one-off questions
(a sum, a joke, a quick command) that nobody will bring up again."""

FILES = {
    "user": ("USER.md", "# USER.md: la familia\n\n"
             "Quién es quién: nombres, parentescos, cumpleaños, gustos y cómo les gusta que los traten.\n"
             "Se actualiza solo al final de cada plática; se puede editar a mano (un dato por línea \"- \").\n"),
    "memory": ("MEMORY.md", "# MEMORY.md: memoria de largo plazo\n\n"
               "Planes y fechas, chistes internos, lo que pidieron recordar.\n"
               "Se actualiza solo al final de cada plática; se puede editar a mano (un dato por línea \"- \").\n"),
}
DAILY_DIR = "memory"


class Memory:
    USER_HEADER = "## Lo que sabes de la familia (úsalo para bromear y personalizar)"
    MEMORY_HEADER = "## Lo que tienes guardado: planes, fechas y chistes internos"
    DAILY_HEADER = "## Pláticas recientes"

    def __init__(self, path, llm=None, name="the robot", max_facts=150, recent_days=2, recent_notes=10):
        self.path = path
        self.llm = llm   # used only for learn(); None keeps the memory read-only
        self.name = name
        self.max_facts = max_facts
        self.recent_days = recent_days     # daily notes in the prompt (OpenClaw: today and yesterday)
        self.recent_notes = recent_notes   # at most this many lines from them
        self._lock = threading.Lock()         # guards facts
        self._learn_lock = threading.Lock()   # one learn() at a time, so fact ids stay valid
        self._preambles = {key: FILES[key][1] for key in FILES}
        self._migrate_json()
        self.facts = []   # [{"file": "user" | "memory", "text": ...}], in file order
        for key in FILES:
            preamble, bullets = self._read_facts(key)
            self._preambles[key] = preamble
            self.facts += [{"file": key, "text": t} for t in bullets]

    # ── files ────────────────────────────────────────────────────────

    def _file(self, key):
        return os.path.join(self.path, FILES[key][0])

    def _daily(self, day):
        return os.path.join(self.path, DAILY_DIR, f"{day}.md")

    def _read_facts(self, key):
        try:
            with open(self._file(key), encoding="utf-8") as f:
                lines = f.read().splitlines()
        except FileNotFoundError:
            return FILES[key][1], []
        except Exception as e:
            print(f"(memoria: no se pudo leer {self._file(key)}: {e})")
            return FILES[key][1], []
        bullets = [i for i, line in enumerate(lines) if line.startswith("- ")]
        if not bullets:
            return "\n".join(lines).rstrip() + "\n", []
        preamble = "\n".join(lines[:bullets[0]]).rstrip() + "\n"
        return preamble, [lines[i][2:].strip() for i in bullets if lines[i][2:].strip()]

    def _write_facts(self, key, facts):
        bullets = "".join(f"- {f['text']}\n" for f in facts if f["file"] == key)
        _write(self._file(key), self._preambles[key] + ("\n" + bullets if bullets else ""))

    def _append_daily(self, line, day=None):
        day = day or date.today().isoformat()
        path = self._daily(day)
        try:
            with open(path, encoding="utf-8") as f:
                text = f.read().rstrip("\n") + "\n"
        except FileNotFoundError:
            text = f"# {day}\n"
        if not any(l.startswith("- ") for l in text.splitlines()):
            text += "\n"
        _write(path, text + f"- {line}\n")

    def _recent_daily(self):
        try:
            days = sorted(n for n in os.listdir(os.path.join(self.path, DAILY_DIR)) if n.endswith(".md"))
        except FileNotFoundError:
            return []
        notes = []
        for name in days[-self.recent_days:]:
            with open(os.path.join(self.path, DAILY_DIR, name), encoding="utf-8") as f:
                notes += [f"{name[:-3]} {line[2:].strip()}" for line in f.read().splitlines() if line.startswith("- ")]
        return notes[-self.recent_notes:]

    def _migrate_json(self):
        """One-time move from the old single-file store (<path>.json) into the workspace."""
        old = self.path.rstrip("/") + ".json"
        if os.path.exists(self._file("memory")) or not os.path.exists(old):
            return
        try:
            with open(old, encoding="utf-8") as f:
                data = json.load(f)
        except Exception as e:
            print(f"(memoria: no se pudo migrar {old}: {e})")
            return
        texts = [f if isinstance(f, str) else f.get("text", "") for f in data.get("facts") or []]
        # the old store didn't separate people from the rest; the model moves them on later updates
        facts = [{"file": "memory", "text": t.strip()} for t in texts if isinstance(t, str) and t.strip()]
        for key in FILES:
            self._write_facts(key, facts)
        for e in data.get("episodes") or []:
            if isinstance(e, dict) and e.get("summary"):
                self._append_daily(e["summary"], day=e.get("date") or date.today().isoformat())
        os.replace(old, old + ".migrated")
        print(f"(memoria: migrada de {old} a {self.path})")

    # ── prompt ───────────────────────────────────────────────────────

    def prompt_section(self):
        with self._lock:
            facts = list(self.facts)
        out = ""
        for key, header in (("user", self.USER_HEADER), ("memory", self.MEMORY_HEADER)):
            lines = [f["text"] for f in facts if f["file"] == key]
            if lines:
                out += "\n" + header + "\n" + "\n".join(f"- {x}" for x in lines) + "\n"
        notes = self._recent_daily()
        if notes:
            out += "\n" + self.DAILY_HEADER + "\n" + "\n".join(f"- {n}" for n in notes) + "\n"
        return out

    # ── learning ─────────────────────────────────────────────────────

    def learn(self, transcript):
        """Update memory from one conversation: a list of (role, text), role "user" or "assistant"."""
        if self.llm is None or not any(role == "user" and text for role, text in transcript):
            return
        with self._learn_lock:
            try:
                edits = self._extract(transcript)
            except Exception as e:
                print(f"(memoria: no se pudo aprender de la plática: {e})")
                return
            self._apply(edits)

    def _extract(self, transcript):
        today = date.today().isoformat()
        with self._lock:
            facts = list(self.facts)
        system = EXTRACT_PROMPT.format(name=self.name, today=today, max_facts=self.max_facts, count=len(facts))
        stored = "\n".join(f"[{i}] ({f['file']}) {f['text']}" for i, f in enumerate(facts, 1)) or "(empty)"
        convo = "\n".join(f"{'User' if role == 'user' else self.name}: {text}" for role, text in transcript if text)
        user = f"Stored facts:\n{stored}\n\nConversation:\n{convo}"
        # chat() rather than prompt(): prompt() hides an API error behind KeyError('choices')
        self.llm.messages = [{"role": "system", "content": system}, {"role": "user", "content": user}]
        data = self.llm.chat(False, response_format={"type": "json_object"}).json()
        if "error" in data:
            raise RuntimeError(data["error"].get("message", data["error"]))
        reply = data["choices"][0]["message"]["content"].strip().removeprefix("```json").removeprefix("```").removesuffix("```")
        edits = json.loads(reply)
        if not isinstance(edits, dict):
            raise ValueError(f"expected a JSON object, got {reply!r}")
        return edits

    def _apply(self, edits):
        with self._lock:
            facts = [dict(f) for f in self.facts]
            for u in _list(edits.get("update")):
                i, text = _index(u.get("id") if isinstance(u, dict) else None, len(facts)), _text(u)
                if i is not None and text:
                    facts[i] = {"file": _file_key(u.get("file"), facts[i]["file"]), "text": text}
            drop = {_index(i, len(facts)) for i in _list(edits.get("delete"))}
            facts = [f for i, f in enumerate(facts) if i not in drop]
            added = []
            for a in _list(edits.get("add")):
                text = a if isinstance(a, str) else _text(a)
                if text.strip():
                    added.append({"file": _file_key(a.get("file") if isinstance(a, dict) else None), "text": text.strip()})
            facts += added
            facts = _trim(facts, self.max_facts)
            # file order, as a reload would read them back, so fact ids stay stable
            facts = [f for key in FILES for f in facts if f["file"] == key]
            changed = facts != self.facts
            if changed:
                self.facts = facts
                for key in FILES:
                    self._write_facts(key, facts)
            summary = edits.get("summary")
            if isinstance(summary, str) and summary.strip():
                self._append_daily(f"{datetime.now():%H:%M} {summary.strip()}")
        for a in added:
            print(f"(memoria guardada en {FILES[a['file']][0]}: {a['text']})")
        if changed and not added:
            print("(memoria actualizada)")


def _write(path, text):
    """Atomic and durable: the Pi browns out, and a torn write would empty the file."""
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    try:
        with open(tmp, "w", encoding="utf-8") as f:
            f.write(text)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, path)
        fd = os.open(os.path.dirname(path), os.O_RDONLY)
        try:
            os.fsync(fd)
        finally:
            os.close(fd)
    except Exception as e:
        print(f"(memoria: no se pudo guardar {path}: {e})")


def _trim(facts, limit):
    """The model ignored the limit: drop the oldest facts, the top of MEMORY.md
    first and USER.md only after it is empty."""
    excess = len(facts) - limit
    drop = set()
    for key in ("memory", "user"):
        if excess <= 0:
            break
        idx = [i for i, f in enumerate(facts) if f["file"] == key][:excess]
        drop.update(idx)
        excess -= len(idx)
    return [f for i, f in enumerate(facts) if i not in drop]


def _file_key(value, default="memory"):
    return value if value in FILES else default


def _list(value):
    return value if isinstance(value, list) else []


def _index(fact_id, count):
    """Prompt ids are 1-based; return the list index, or None if it is not a valid id."""
    try:
        i = int(fact_id) - 1
    except (TypeError, ValueError):
        return None
    return i if 0 <= i < count else None


def _text(update):
    text = update.get("text") if isinstance(update, dict) else None
    return text.strip() if isinstance(text, str) else ""
