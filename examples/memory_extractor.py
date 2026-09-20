"""Memory extraction through the Agent SDK: Haiku with a JSON schema.

`memory.Memory.learn` hands the extraction prompt (memory.EXTRACT_PROMPT) and
the conversation to whatever it was given as `llm`. `AgentExtractor` is the
Anthropic version of that: one one-shot `claude_agent_sdk.query` on a small
model with `output_format` set to a JSON schema, so the edits come back typed
in `ResultMessage.structured_output` instead of scraped out of a text reply.

No tools, no MCP servers, no settings from disk: the CLI runs as the agent's
unprivileged user (same as petronilo_agent.AgentBrain) with just the prompt.
"""
import asyncio
import json
import os
import threading

from claude_agent_sdk import ClaudeAgentOptions, ResultMessage, query

FACT_FILE = {"type": "string", "enum": ["user", "memory"]}

# What memory.Memory._apply reads: add / update / delete edits plus a summary line.
SCHEMA = {
    "type": "object",
    "properties": {
        "add": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {"file": FACT_FILE, "text": {"type": "string"}},
                "required": ["file", "text"],
                "additionalProperties": False,
            },
        },
        "update": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {"id": {"type": "integer"}, "text": {"type": "string"}, "file": FACT_FILE},
                "required": ["id", "text"],
                "additionalProperties": False,
            },
        },
        "delete": {"type": "array", "items": {"type": "integer"}},
        "summary": {"type": "string"},
    },
    "required": ["add", "update", "delete", "summary"],
    "additionalProperties": False,
}


class AgentExtractor:
    """`extract_json(system, user)` for memory.Memory: one structured-output
    query through the Claude Code CLI.

    `max_turns` is 3, not 1: the CLI delivers structured output through an
    internal tool call, so a one-turn cap can end the run before the JSON is
    produced. `on_cost(total_cost_usd)` is called after each run so the caller
    (AgentBrain's daily budget) can count it."""

    def __init__(self, api_key, workspace, user=None, model="claude-haiku-4-5", max_turns=3,
                 on_cost=None, timeout=120):
        self.api_key = api_key
        self.workspace = workspace
        self.user = user
        self.model = model
        self.max_turns = max_turns
        self.on_cost = on_cost
        self.timeout = timeout

    def options(self, system):
        env = {}
        if self.api_key:
            env["ANTHROPIC_API_KEY"] = self.api_key
        if self.user:
            # subprocess user= switches uid but keeps root's HOME
            env["HOME"] = os.path.expanduser(f"~{self.user}")
        return ClaudeAgentOptions(
            model=self.model,
            system_prompt=system,
            tools=[],                    # no built-in tools: text in, JSON out
            mcp_servers={},
            strict_mcp_config=True,      # nor any MCP server the CLI would load on its own
            setting_sources=[],          # nothing from disk (SDK isolation mode)
            permission_mode="dontAsk",
            max_turns=self.max_turns,
            cwd=self.workspace,
            user=self.user,
            env=env,
            output_format={"type": "json_schema", "schema": SCHEMA},
        )

    def extract_json(self, system, user):
        """Run the extraction and return the edits dict. Raises on failure."""
        return _run(self._extract(system, user), self.timeout)

    async def _extract(self, system, user):
        result = None
        async for msg in query(prompt=user, options=self.options(system)):
            if isinstance(msg, ResultMessage):
                result = msg
        if result is None:
            raise RuntimeError("the extraction run ended without a result")
        cost = getattr(result, "total_cost_usd", None)
        if self.on_cost is not None and cost:
            try:
                self.on_cost(float(cost))
            except Exception as e:
                print(f"(memoria: no se pudo contar el costo: {e})")
        out = getattr(result, "structured_output", None)
        if isinstance(out, dict):
            return out
        text = getattr(result, "result", None)
        if isinstance(text, str) and text.strip():
            try:
                parsed = json.loads(text.strip().removeprefix("```json").removeprefix("```").removesuffix("```"))
            except ValueError:
                parsed = None
            if isinstance(parsed, dict):
                return parsed
        errors = getattr(result, "errors", None) or []
        raise RuntimeError(f"extraction failed: {getattr(result, 'subtype', '?')} {' '.join(map(str, errors))}".strip())


def _run(coro, timeout):
    """Run `coro` to completion from a plain thread. learn() runs on a
    background thread with no event loop, so asyncio.run is the normal case;
    if this thread already has a running loop, use a private one on a helper
    thread instead of nesting."""
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(asyncio.wait_for(coro, timeout))
    box = {}

    def target():
        try:
            box["value"] = asyncio.run(asyncio.wait_for(coro, timeout))
        except BaseException as e:   # noqa: BLE001 - re-raised in the caller
            box["error"] = e

    t = threading.Thread(target=target, daemon=True)
    t.start()
    t.join()
    if "error" in box:
        raise box["error"]
    return box["value"]
