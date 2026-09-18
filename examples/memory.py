"""Long-term memory for the voice assistant, learned automatically.

When a conversation ends, `Memory.learn(transcript)` sends the transcript and
the stored facts to an LLM, which answers with edits (add / update / delete)
and a one-line summary of the conversation. `prompt_section()` renders what is
stored for the system prompt. Everything lives in one JSON file.
"""
import json
import os
import threading
from datetime import date

EXTRACT_PROMPT = """You maintain the long-term memory of {name}, a voice assistant robot that lives with a family.
Today is {today}. Read the conversation and update the memory.

Keep facts that will still matter in future conversations: who people are (names, relationships, ages,
birthdays), what they like and dislike, plans and dates, pets, running jokes, and anything someone asked
to be remembered. Skip small talk, the robot's own jokes and trivia, things that only matter right now,
and secrets such as passwords or card numbers. The user side is speech-to-text and can be garbled: do not
store a name or detail you are unsure was heard correctly.

Write each fact as one short standalone sentence in the language of the conversation, saying who it is
about, with relative dates turned into absolute ones ("mañana" -> the actual date). If something is a secret
or a surprise, say in the fact who must not find out. Update a fact when the
conversation changes or corrects it, delete it when it turned out wrong or someone asks to forget it, and
never add a duplicate. Memory holds at most {max_facts} facts and has {count} now; when it is close to
full, merge related facts and drop the least useful ones.

Reply with JSON only, in this shape (empty lists when nothing changes):
{{"add": ["fact"], "update": [{{"id": 3, "text": "fact"}}], "delete": [5], "summary": "..."}}
"summary" is one sentence on what the conversation was about, or "" for small talk and one-off questions
(a sum, a joke, a quick command) that nobody will bring up again."""


class Memory:
    FACTS_HEADER = "## Lo que sabes de la familia y chistes internos (úsalo para bromear y personalizar)"
    EPISODES_HEADER = "## Pláticas recientes"

    def __init__(self, path, llm=None, name="the robot", max_facts=150, max_episodes=30, recent_episodes=5):
        self.path = path
        self.llm = llm   # used only for learn(); None keeps the memory read-only
        self.name = name
        self.max_facts = max_facts
        self.max_episodes = max_episodes
        self.recent_episodes = recent_episodes
        self._lock = threading.Lock()         # guards facts/episodes
        self._learn_lock = threading.Lock()   # one learn() at a time, so fact ids stay valid
        self.facts, self.episodes = self._load()

    def _load(self):
        try:
            with open(self.path, encoding="utf-8") as f:
                data = json.load(f)
        except FileNotFoundError:
            return [], []
        except Exception as e:
            print(f"(memoria: no se pudo leer {self.path}: {e})")
            return [], []
        facts = []
        for fact in data.get("facts") or []:
            if isinstance(fact, str):   # the old format was a plain list of strings
                fact = {"text": fact, "updated": ""}
            if isinstance(fact, dict) and fact.get("text"):
                facts.append({"text": fact["text"], "updated": fact.get("updated", "")})
        episodes = [e for e in data.get("episodes") or [] if isinstance(e, dict) and e.get("summary")]
        return facts, episodes

    def _save(self):
        data = {"facts": self.facts, "episodes": self.episodes}
        tmp = self.path + ".tmp"
        try:
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
            os.replace(tmp, self.path)
        except Exception as e:
            print(f"(memoria: no se pudo guardar: {e})")

    def prompt_section(self):
        with self._lock:
            facts = [f["text"] for f in self.facts]
            episodes = self.episodes[-self.recent_episodes:]
        out = ""
        if facts:
            out += "\n" + self.FACTS_HEADER + "\n" + "\n".join(f"- {x}" for x in facts) + "\n"
        if episodes:
            out += ("\n" + self.EPISODES_HEADER + "\n"
                    + "\n".join(f"- {e['date']}: {e['summary']}" for e in episodes) + "\n")
        return out

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
            facts = [f["text"] for f in self.facts]
        system = EXTRACT_PROMPT.format(name=self.name, today=today, max_facts=self.max_facts, count=len(facts))
        stored = "\n".join(f"[{i}] {text}" for i, text in enumerate(facts, 1)) or "(empty)"
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
        today = date.today().isoformat()
        with self._lock:
            facts = list(self.facts)
            for u in _list(edits.get("update")):
                i, text = _index(u.get("id") if isinstance(u, dict) else None, len(facts)), _text(u)
                if i is not None and text:
                    facts[i] = {"text": text, "updated": today}
            drop = {_index(i, len(facts)) for i in _list(edits.get("delete"))}
            facts = [f for i, f in enumerate(facts) if i not in drop]
            added = [t.strip() for t in _list(edits.get("add")) if isinstance(t, str) and t.strip()]
            facts += [{"text": t, "updated": today} for t in added]
            if len(facts) > self.max_facts:
                # the model ignored the limit: drop the facts that went longest without an update
                keep = sorted(range(len(facts)), key=lambda i: facts[i]["updated"])[-self.max_facts:]
                facts = [facts[i] for i in sorted(keep)]
            summary = edits.get("summary")
            if isinstance(summary, str) and summary.strip():
                self.episodes = (self.episodes + [{"date": today, "summary": summary.strip()}])[-self.max_episodes:]
            changed = facts != self.facts
            self.facts = facts
            self._save()
        for t in added:
            print(f"(memoria guardada: {t})")
        if changed and not added:
            print("(memoria actualizada)")


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
