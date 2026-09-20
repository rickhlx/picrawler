"""Claude Agent SDK brain for VoiceActiveCrawler.

The agent (Claude Code, driven by claude-agent-sdk) gets shell commands,
skills, MCP servers and the robot's own tools, and streams its spoken text
back sentence by sentence. Two processes, two privilege levels:

- The Claude Code CLI runs as an unprivileged user (``user=``) in its own
  workspace, so Bash, file writes and external MCP servers can't touch the
  robot or the rest of the Pi. ``agent_policy`` allowlists what it may do on
  top of that.
- The robot tools are an in-process MCP server: they run here, in the root
  voice service that owns the servos, camera and sonar.

One conversation (wake word to silence) is one agent session; the system
prompt, with the latest memory, is fixed when the session starts.

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

    @tool("look", "Take a photo with the camera in your face and see it.", {})
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

    return [move, find, look, sensors]


class AgentBrain:
    """Runs a ClaudeSDKClient on a private event loop so the synchronous voice
    loop can call ``ask`` and iterate the reply as text chunks.

    ``max_budget_usd`` caps one conversation's spend (the SDK cuts the session
    off mid-answer). ``daily_budget_usd`` refuses to start a new conversation
    once ``spent_today`` reaches it; the caller catches ``BudgetExceeded`` and
    speaks a canned phrase instead."""

    def __init__(self, *, api_key, workspace, user=None, commands=(), model="claude-opus-5",
                 effort="low", mcp_config=None, skills="all", max_turns=12,
                 max_budget_usd=None, daily_budget_usd=None):
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
        self.spent_today = 0.0
        self._spent_day = datetime.date.today()
        self.va = None
        self._client = None
        self._mcp_names = set()
        self._connecting = None  # asyncio.Lock, made on the loop
        self._read_roots = [os.path.expanduser(f"~{user}/.claude/skills")] if user else []
        self._loop = asyncio.new_event_loop()
        threading.Thread(target=self._loop.run_forever, daemon=True).start()

    def attach(self, va):
        self.va = va
        self._tools = robot_tools(va)
        self._robot_names = {f"mcp__{ROBOT}__{t.name}" for t in self._tools}

    # -- public, called from the voice loop ---------------------------------

    def start(self, system_prompt):
        """Open the conversation's session in the background (the CLI takes a
        few seconds to start), so it is ready by the time the question is heard."""
        asyncio.run_coroutine_threadsafe(self._connect(system_prompt), self._loop)

    def ask(self, text, system_prompt):
        """Yield the reply's text as it streams (tool calls run in between)."""
        chunks = queue.Queue()
        asyncio.run_coroutine_threadsafe(self._ask(text, system_prompt, chunks), self._loop)
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

    def _options(self, system_prompt):
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
            kwargs["max_budget_usd"] = self.max_budget_usd
        return ClaudeAgentOptions(
            model=self.model,
            effort=self.effort,
            system_prompt=system_prompt,
            cwd=self.workspace,
            user=self.user,
            env=env,
            mcp_servers={ROBOT: create_sdk_mcp_server(ROBOT, tools=self._tools), **external},
            # A hook, not can_use_tool: allow rules in settings files approve a
            # tool before can_use_tool is asked, but every call passes the hook.
            # dontAsk denies whatever the hook doesn't decide; nobody can answer.
            hooks={"PreToolUse": [HookMatcher(hooks=[self._gate])]},
            permission_mode="dontAsk",
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

    async def _connect(self, system_prompt):
        self._connecting = self._connecting or asyncio.Lock()
        async with self._connecting:
            if self._client is not None:
                return
            options, self._mcp_names = self._options(system_prompt)
            client = ClaudeSDKClient(options)
            try:
                await client.connect()
            except Exception as e:
                print(f"(agente: no arrancó: {e})")
                return
            self._client = client

    def _roll_day(self):
        today = datetime.date.today()
        if today != self._spent_day:
            self._spent_day = today
            self.spent_today = 0.0

    def _add_cost(self, cost):
        self._roll_day()
        self.spent_today += cost

    async def _ask(self, text, system_prompt, chunks):
        try:
            self._roll_day()
            if self.daily_budget_usd is not None and self.spent_today >= self.daily_budget_usd:
                # Don't even connect; the session stays closed for next time.
                chunks.put(BudgetExceeded(f"daily budget of ${self.daily_budget_usd:.2f} spent"))
                return
            await self._connect(system_prompt)
            if self._client is None:
                raise RuntimeError("the agent session did not start")
            await self._client.query(text)
            async for msg in self._client.receive_response():
                if isinstance(msg, StreamEvent) and msg.parent_tool_use_id is None:
                    ev = msg.event
                    if ev.get("type") == "content_block_delta" and ev["delta"].get("type") == "text_delta":
                        chunks.put(ev["delta"]["text"])
                    elif ev.get("type") == "content_block_start" and ev["content_block"].get("type") == "text":
                        # a new text block after a tool call: keep sentences apart
                        chunks.put(" ")
                elif isinstance(msg, ResultMessage):
                    cost = msg.total_cost_usd or 0
                    self._add_cost(cost)
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

    async def _disconnect(self):
        client, self._client = self._client, None
        if client is not None:
            try:
                await client.disconnect()
            except Exception as e:
                print(f"(agente: cierre falló: {e})")
