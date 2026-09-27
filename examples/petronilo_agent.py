"""Claude Agent SDK brain for VoiceActiveCrawler.

The agent (Claude Code, driven by claude-agent-sdk) gets shell commands,
skills, MCP servers and the robot's own tools, and streams its spoken text
back sentence by sentence. Two processes, two privilege levels:

- The Claude Code CLI runs as an unprivileged user (``user=``) in its own
  workspace, so Bash, file writes and external MCP servers can't touch the
  robot or the rest of the Pi. ``agent_policy`` allowlists what it may do on
  top of that.
- The robot tools (``move``, ``find``, ``look``, ``sensors``, ``remember``,
  ``recall``, ``forget``, ``remind``, ``reminders``, ``cancel_reminder``) are
  an in-process MCP server: they run here, in the root voice service that
  owns the servos, camera, sonar, memory (``memory.py``) and scheduler
  (``scheduler.py``).

One conversation (wake word to silence) is one agent session. If the next
one starts within ``resume_within`` seconds, the session is resumed instead
(``resume=``), so he still has the last exchange word for word; the system
prompt is sent with ``snapshot: False`` so the freshly learned memory reaches
a resumed session too. The date, time and battery travel in a
``UserPromptSubmit`` hook with every message, which keeps the system prompt
byte-stable for the prompt cache.

Spend is capped two ways: ``max_budget_usd`` stops a single conversation
mid-session, and ``daily_budget_usd`` refuses to start a new one once the
day's total is spent.
"""
import asyncio
import base64
import datetime
import json
import os
import queue
import threading
import time

from claude_agent_sdk import (
    ClaudeAgentOptions,
    ClaudeSDKClient,
    HookMatcher,
    ResultMessage,
    StreamEvent,
    create_sdk_mcp_server,
    tool,
)

import agent_policy

ROBOT = "robot"
_END = object()

# The policy would deny these anyway; removing them means the model never
# spends a turn trying. AskUserQuestion would also just hang under dontAsk,
# since nobody is there to answer it.
DISALLOWED_TOOLS = ["Agent", "AskUserQuestion", "ComputerUse", "FileSearch", "CodeExecution"]

# The find tool walks for up to a minute or more, longer than the CLI's
# default MCP tool timeout.
MCP_TOOL_TIMEOUT_MS = 180_000


class BudgetExceeded(RuntimeError):
    """Raised by AgentBrain.ask when the day's budget is already spent."""


def _text(s, error=False):
    out = {"content": [{"type": "text", "text": s}]}
    if error:
        out["is_error"] = True
    return out


def robot_tools(va):
    """In-process tools bound to a VoiceActiveCrawler."""
    actions = sorted(va.ACTION_MAP)

    @tool("move", "Move the body while you keep talking: one of " + ", ".join(actions) + ". "
          "Returns at once; the move runs in the background.",
          {"type": "object", "properties": {"action": {"type": "string", "enum": actions}},
           "required": ["action"]})
    async def move(args):
        return _text(*va.queue_tool_action(args["action"]))

    @tool("find", "Turn in place until the camera sees the object, walk up to it and stop in front. "
          "Takes up to a minute; returns what happened.",
          {"object": str})
    async def find(args):
        return _text(await asyncio.to_thread(va.seek, args["object"]))

    @tool("where", "Look around for something and say where it is, without walking to it: turn in "
          "place taking photos until you spot it, then stop facing it. Use this for \"where is X\" "
          "questions; use find when you should go to it. Takes up to a minute.",
          {"object": str})
    async def where(args):
        return _text(json.dumps(await asyncio.to_thread(va.locate, args["object"]),
                                ensure_ascii=False))

    @tool("look", "Take a photo with the camera in your face and see it. If the question already "
          "came with a photo, answer from that one instead of calling this.", {})
    async def look(args):
        path = await asyncio.to_thread(va.snapshot)
        if not path:
            return _text("The camera is off.", error=True)
        with open(path, "rb") as f:
            data = base64.standard_b64encode(f.read()).decode()
        return {"content": [{"type": "image", "data": data, "mimeType": "image/jpeg"}]}

    @tool("sensors", "Battery voltage and the ultrasonic distance to whatever is in front.", {})
    async def sensors(args):
        return _text(json.dumps(await asyncio.to_thread(va.sensor_readings)))

    @tool("remember", "Save one durable fact to the robot's long-term memory, on request or when "
          "something worth keeping comes up. Write it in Spanish, as one short standalone "
          "sentence, with absolute dates instead of relative ones (\"mañana\" -> the actual "
          "date). Family members (who they are, relationships, birthdays, likes) go in "
          "\"family\"; everything else durable (plans, requests, decisions) goes in \"other\".",
          {"type": "object", "properties": {
              "text": {"type": "string"},
              "about": {"type": "string", "enum": ["family", "other"]}},
           "required": ["text", "about"]})
    async def remember(args):
        file = "user" if args["about"] == "family" else "memory"
        return _text(va.memory.add_fact(args["text"], file))

    @tool("recall", "Search the robot's long-term memory, the daily notes and past conversations "
          "word for word for something.",
          {"query": str})
    async def recall(args):
        results = va.memory.search(args["query"])
        return _text("\n".join(results) if results else "Nothing stored about that.")

    @tool("forget", "Remove every stored fact matching a query from the robot's long-term memory, "
          "e.g. when asked to forget something.",
          {"query": str})
    async def forget(args):
        n = va.memory.remove_fact(args["query"])
        return _text(f"Forgot {n} fact(s)." if n else "Nothing matched.")

    @tool("remind", "Schedule a reminder or task for later. \"when\" is a local ISO-8601 date "
          "and time, e.g. 2026-09-21T08:00 (the current date and time are in the system "
          "prompt). For kind \"say\", \"text\" is exactly what the robot will say aloud when "
          "the time comes: write it in Petronilo's own voice, in Spanish. For kind \"ask\", "
          "\"text\" is a task description the agent will carry out when the time comes.",
          {"type": "object", "properties": {
              "when": {"type": "string"},
              "text": {"type": "string"},
              "kind": {"type": "string", "enum": ["say", "ask"]},
              "repeat": {"type": "string", "enum": ["none", "daily", "weekly"]}},
           "required": ["when", "text", "kind", "repeat"]})
    async def remind(args):
        if va.scheduler is None:
            return _text("No scheduler configured.", error=True)
        repeat = None if args["repeat"] == "none" else args["repeat"]
        try:
            job = va.scheduler.add(args["when"], args["text"], args["kind"], repeat)
        except ValueError as e:
            return _text(str(e), error=True)
        return _text(va.scheduler.describe(job))

    @tool("reminders", "List every pending reminder and task.", {})
    async def reminders(args):
        if va.scheduler is None:
            return _text("No scheduler configured.", error=True)
        jobs = va.scheduler.list()
        return _text("\n".join(va.scheduler.describe(j) for j in jobs) if jobs else "No reminders.")

    @tool("cancel_reminder", "Cancel a pending reminder or task by its id.", {"id": str})
    async def cancel_reminder(args):
        if va.scheduler is None:
            return _text("No scheduler configured.", error=True)
        ok = va.scheduler.remove(args["id"])
        return _text("Cancelled." if ok else "No reminder with that id.", error=not ok)

    return [move, find, where, look, sensors, remember, recall, forget,
            remind, reminders, cancel_reminder]


class AgentBrain:
    """Runs a ClaudeSDKClient on a private event loop so the synchronous voice
    loop can call ``ask`` and iterate the reply as text chunks.

    ``max_budget_usd`` caps one conversation's spend (the SDK cuts the session
    off mid-answer). ``daily_budget_usd`` refuses to start a new conversation
    once ``spent_today`` reaches it; the caller catches ``BudgetExceeded`` and
    speaks a canned phrase instead."""

    def __init__(self, *, api_key, workspace, user=None, commands=(), model="claude-opus-5-5",
                 effort="low", mcp_config=None, skills="all", max_turns=12,
                 max_budget_usd=None, daily_budget_usd=None, fallback_model=None,
                 resume_within=1800, state_path=None):
        self.api_key = api_key
        self.workspace = workspace
        self.user = user
        self.commands = set(commands)
        self.model = model
        self.effort = effort
        self.mcp_config = mcp_config
        self.skills = skills
        self.max_turns = max_turns
        self.max_budget_usd = max_budget_usd
        self.daily_budget_usd = daily_budget_usd
        # Used by the CLI when the main model is overloaded or failing, so he stays
        # in the agent with his tools instead of dropping to the legacy LLM.
        self.fallback_model = fallback_model
        # A new session started within this many seconds of the last one closing
        # resumes it (0 or None: always start fresh). The last session id and
        # when it closed are kept in state_path (JSON) across service restarts.
        self.resume_within = resume_within or 0
        self.state_path = state_path
        self.last_session_id = None
        self.last_session_end = 0.0
        # What last_session_id had spent in total when it closed. None means we
        # never recorded it (an older state file), which _add_cost handles by
        # taking the resumed session's first report as the baseline.
        self.last_session_cost = None
        self._load_state()
        self.spent_today = 0.0
        self._spent_day = datetime.date.today()
        # Running total the current session has reported so far (see _add_cost).
        # A resumed session carries on from what it already spent, not from 0.
        self._session_cost = 0.0
        self._cost_unknown = False
        self._session_id = None
        # when the conversation this connection resumed had ended (None: fresh)
        self._resumed_end = None
        self.va = None
        self._client = None
        self._mcp_names = set()
        self._connecting = None  # asyncio.Lock, made on the loop
        self._read_roots = [os.path.expanduser(f"~{user}/.claude/skills")] if user else []
        self._loop = asyncio.new_event_loop()
        threading.Thread(target=self._loop.run_forever, daemon=True).start()

    # -- resume state ---------------------------------------------------------

    def _load_state(self):
        if not self.state_path:
            return
        try:
            with open(self.state_path, encoding="utf-8") as f:
                data = json.load(f)
            sid, end = data.get("session_id"), data.get("ended")
            if isinstance(sid, str) and sid and isinstance(end, (int, float)):
                self.last_session_id, self.last_session_end = sid, float(end)
                cost = data.get("cost")
                self.last_session_cost = (
                    float(cost) if isinstance(cost, (int, float)) else None)
        except FileNotFoundError:
            pass
        except Exception as e:
            print(f"(agente: no se pudo leer {self.state_path}: {e})")

    def _save_state(self):
        if not self.state_path:
            return
        try:
            os.makedirs(os.path.dirname(os.path.abspath(self.state_path)), exist_ok=True)
            tmp = self.state_path + ".tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump({"session_id": self.last_session_id,
                           "ended": self.last_session_end,
                           "cost": self.last_session_cost}, f)
            os.replace(tmp, self.state_path)
        except Exception as e:
            print(f"(agente: no se pudo guardar {self.state_path}: {e})")

    def _remember_session(self, session_id, cost=None):
        self.last_session_id = session_id
        self.last_session_end = time.time()
        self.last_session_cost = cost
        self._save_state()

    def _forget_session(self):
        self.last_session_id = None
        self.last_session_end = 0.0
        self.last_session_cost = None
        self._save_state()

    def resume_id(self, now=None):
        """The session to resume, or None when there is none or it is too old."""
        if not self.last_session_id or not self.resume_within:
            return None
        now = time.time() if now is None else now
        if now - self.last_session_end < self.resume_within:
            return self.last_session_id
        return None

    def attach(self, va):
        self.va = va
        self._tools = robot_tools(va)
        self._robot_names = {f"mcp__{ROBOT}__{t.name}" for t in self._tools}

    # -- public, called from the voice loop ---------------------------------

    def start(self, system_prompt):
        """Open the conversation's session in the background (the CLI takes a
        few seconds to start), so it is ready by the time the question is heard."""
        asyncio.run_coroutine_threadsafe(self._connect(system_prompt), self._loop)

    def ask(self, text, system_prompt, image_path=None):
        """Yield the reply's text as it streams (tool calls run in between).
        ``image_path`` (JPEG) is sent with the question, for visual ones."""
        chunks = queue.Queue()
        asyncio.run_coroutine_threadsafe(self._ask(text, system_prompt, chunks, image_path), self._loop)
        while (chunk := chunks.get()) is not _END:
            if isinstance(chunk, BaseException):
                raise chunk
            yield chunk

    def end(self):
        """Close the conversation's session; the next ask starts a new one."""
        asyncio.run_coroutine_threadsafe(self._disconnect(), self._loop).result(timeout=30)

    # -- event loop side ------------------------------------------------------

    def _external_mcp(self):
        if not self.mcp_config or not os.path.exists(self.mcp_config):
            return {}
        with open(self.mcp_config) as f:
            return json.load(f).get("mcpServers", {})

    def _options(self, system_prompt, resume=None):
        external = self._external_mcp()
        # Load every tool up front: deferring MCP tools behind ToolSearch costs
        # an extra model turn, which is dead air when the answer is spoken.
        env = {"ENABLE_TOOL_SEARCH": "false"}
        if self.api_key:
            env["ANTHROPIC_API_KEY"] = self.api_key
        if self.user:
            # subprocess user= switches uid but keeps root's HOME
            env["HOME"] = os.path.expanduser(f"~{self.user}")
        # The find tool can take over a minute; the CLI's default MCP tool
        # timeout is shorter than that.
        env["MCP_TOOL_TIMEOUT"] = str(MCP_TOOL_TIMEOUT_MS)
        kwargs = {}
        if self.max_budget_usd is not None:
            # The CLI counts a resumed session's whole running total against
            # this cap, so raise it by what the session already spent; the cap
            # is meant to bound one conversation, not the session's history.
            kwargs["max_budget_usd"] = self.max_budget_usd + (
                (self.last_session_cost or 0.0) if resume else 0.0)
        if self.fallback_model:
            kwargs["fallback_model"] = self.fallback_model
        if resume:
            kwargs["resume"] = resume
        return ClaudeAgentOptions(
            model=self.model,
            effort=self.effort,
            # snapshot False: a resumed session gets the prompt rebuilt with the
            # memory learned since, instead of the one it recorded when it began
            # (needs Claude Code CLI 2.1.257+, bundled with claude-agent-sdk 0.2.153+).
            system_prompt={"type": "custom", "prompt": system_prompt, "snapshot": False},
            cwd=self.workspace,
            user=self.user,
            env=env,
            mcp_servers={ROBOT: create_sdk_mcp_server(ROBOT, tools=self._tools), **external},
            # A hook, not can_use_tool: allow rules in settings files approve a
            # tool before can_use_tool is asked, but every call passes the hook.
            # dontAsk denies whatever the hook doesn't decide; nobody can answer.
            hooks={
                "PreToolUse": [HookMatcher(hooks=[self._gate])],
                # date, time and battery with every message, not in the system prompt
                "UserPromptSubmit": [HookMatcher(hooks=[self._turn_context])],
                "PreCompact": [HookMatcher(hooks=[self._on_compact])],
            },
            permission_mode="dontAsk",
            stderr=self._stderr,
            skills=self.skills,
            include_partial_messages=True,
            max_turns=self.max_turns,
            # Only the agent user's own settings and skills, nothing from the
            # writable workspace: a CLAUDE.md or .claude/ dropped there would
            # shape every later session.
            setting_sources=["user"],
            disallowed_tools=DISALLOWED_TOOLS,
            **kwargs,
        ), set(external)

    async def _gate(self, hook_input, tool_use_id, context):
        name, args = hook_input["tool_name"], hook_input.get("tool_input") or {}
        ok, reason = agent_policy.verdict(
            name, args, workspace=self.workspace, commands=self.commands,
            robot_tools=self._robot_names, mcp_servers=self._mcp_names, read_roots=self._read_roots)
        print(f"(tool {name}: {'ok' if ok else 'denied: ' + reason})", flush=True)
        decision = {"hookEventName": "PreToolUse", "permissionDecision": "allow" if ok else "deny"}
        if reason:
            decision["permissionDecisionReason"] = reason
        return {"hookSpecificOutput": decision}

    async def _turn_context(self, hook_input, tool_use_id, context):
        """UserPromptSubmit: the current date, time and battery ride along with
        every message, so they are right on every turn of a long or resumed
        session and the system prompt stays byte-stable for the cache."""
        text = ""
        try:
            if self.va is not None:
                text = await asyncio.to_thread(self.va.turn_context)
        except Exception as e:
            print(f"(agente: contexto del turno falló: {e})")
        if not text:
            return {}
        return {"hookSpecificOutput": {"hookEventName": "UserPromptSubmit", "additionalContext": text}}

    async def _on_compact(self, hook_input, tool_use_id, context):
        print(f"(agente: compactando la sesión, trigger={hook_input.get('trigger')})", flush=True)
        return {}

    @staticmethod
    def _stderr(line):
        line = (line or "").strip()
        if line:
            print(f"(agente cli: {line})", flush=True)

    async def _connect(self, system_prompt):
        self._connecting = self._connecting or asyncio.Lock()
        async with self._connecting:
            if self._client is not None:
                # The next session is prewarmed right after a conversation ends,
                # so at connect time the resume is always inside the window; check
                # again now, at the next wake word, so a long gap starts fresh.
                if (self._resumed_end is not None
                        and time.time() - self._resumed_end >= self.resume_within):
                    print("(agente: la sesión retomada ya es vieja; empiezo una nueva)")
                    await self._disconnect(remember=False)
                    self._forget_session()
                else:
                    return
            resume = self.resume_id()
            for attempt in (resume, None) if resume else (None,):
                options, self._mcp_names = self._options(system_prompt, resume=attempt)
                client = ClaudeSDKClient(options)
                try:
                    await client.connect()
                except Exception as e:
                    if attempt:
                        # the transcript may be gone or unreadable: start fresh instead
                        print(f"(agente: no pude retomar la sesión {attempt}: {e})")
                        self._forget_session()
                        continue
                    print(f"(agente: no arrancó: {e})")
                    return
                if attempt:
                    print(f"(agente: retomo la sesión {attempt})")
                self._client = client
                self._session_cost = (self.last_session_cost or 0.0) if attempt else 0.0
                self._cost_unknown = bool(attempt) and self.last_session_cost is None
                self._session_id = attempt
                self._resumed_end = self.last_session_end if attempt else None
                return

    def _roll_day(self):
        today = datetime.date.today()
        if today != self._spent_day:
            self._spent_day = today
            self.spent_today = 0.0

    def _add_cost(self, total):
        """``total`` is what a ResultMessage reports. ClaudeSDKClient runs in
        streaming input mode, where ``total_cost_usd`` is the running total of
        the whole *session* so far, not this turn's cost (Agent SDK docs, "Track
        cost and usage" -> streaming input mode), so only the increase since
        the previous result counts. Resuming does not restart that total, which
        is why _connect seeds _session_cost from the resumed session rather than
        from 0 -- otherwise every resume bills the session's whole history again,
        compounding each time. A drop means the CLI really did reset (a fresh
        session, or a /clear): start over from it. Returns this turn's cost."""
        self._roll_day()
        if self._cost_unknown:
            # Resumed a session from before we recorded spend: take its first
            # report as the baseline instead of billing the history again. This
            # under-counts one turn, which beats over-counting all of them.
            self._cost_unknown = False
            self._session_cost = total
            return 0.0
        turn = total - self._session_cost if total >= self._session_cost else total
        self._session_cost = total
        self.spent_today += turn
        return turn

    @staticmethod
    def _image_block(image_path):
        """Base64 image block for a JPEG, or None if it cannot be read."""
        try:
            with open(image_path, "rb") as f:
                data = base64.standard_b64encode(f.read()).decode()
        except Exception as e:
            print(f"(agente: sin foto para la pregunta: {e})")
            return None
        return {"type": "image", "source": {"type": "base64", "media_type": "image/jpeg", "data": data}}

    @staticmethod
    def user_message(text, image_block=None):
        """The message dict ClaudeSDKClient.query builds for a plain string, with
        the photo (if any) ahead of the text so a visual question needs no look call."""
        content = [image_block, {"type": "text", "text": text}] if image_block else text
        return {"type": "user", "message": {"role": "user", "content": content},
                "parent_tool_use_id": None, "session_id": "default"}

    async def _query(self, text, image_path):
        block = self._image_block(image_path) if image_path else None
        if block is None:
            await self._client.query(text)
            return

        async def one():
            yield self.user_message(text, block)

        await self._client.query(one())

    async def _ask(self, text, system_prompt, chunks, image_path=None):
        try:
            self._roll_day()
            if self.daily_budget_usd is not None and self.spent_today >= self.daily_budget_usd:
                # Don't even connect; the session stays closed for next time.
                chunks.put(BudgetExceeded(f"daily budget of ${self.daily_budget_usd:.2f} spent"))
                return
            await self._connect(system_prompt)
            if self._client is None:
                raise RuntimeError("the agent session did not start")
            await self._query(text, image_path)
            async for msg in self._client.receive_response():
                if isinstance(msg, StreamEvent) and msg.parent_tool_use_id is None:
                    ev = msg.event
                    if ev.get("type") == "content_block_delta" and ev["delta"].get("type") == "text_delta":
                        chunks.put(ev["delta"]["text"])
                    elif ev.get("type") == "content_block_start" and ev["content_block"].get("type") == "text":
                        # a new text block after a tool call: keep sentences apart
                        chunks.put(" ")
                elif isinstance(msg, ResultMessage):
                    if getattr(msg, "session_id", None):
                        self._session_id = msg.session_id
                    cost = self._add_cost(msg.total_cost_usd or 0)
                    if msg.subtype == "error_max_budget_usd":
                        print("(agente: tope de gasto de la conversación alcanzado)")
                    elif msg.is_error:
                        print(f"(agente: {msg.subtype} {msg.result or ''})")
                    print(f"(agente: ${cost:.3f}, {msg.num_turns} turnos, "
                          f"{msg.duration_ms / 1000:.1f}s, hoy ${self.spent_today:.2f})")
        except Exception as e:
            await self._disconnect()
            chunks.put(e)
        finally:
            chunks.put(_END)

    async def _disconnect(self, remember=True):
        client, self._client = self._client, None
        if client is not None:
            if remember and self._session_id:
                # Still unknown means no result came back, so we learnt nothing
                # about this session's spend: keep it unknown rather than 0.
                self._remember_session(
                    self._session_id,
                    None if self._cost_unknown else self._session_cost)
            self._session_id = None
            self._session_cost = 0.0
            self._cost_unknown = False
            self._resumed_end = None
            try:
                await client.disconnect()
            except Exception as e:
                print(f"(agente: cierre falló: {e})")
