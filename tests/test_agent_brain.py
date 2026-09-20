"""AgentBrain (examples/petronilo_agent.py) without the real claude-agent-sdk:
a stub module stands in for it, so the resume window, the state file, the
options it builds, the per-turn hook and the cost accounting can be checked
anywhere. Nothing here talks to a CLI."""
import asyncio
import json
import os
import shutil
import sys
import tempfile
import types
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.realpath(__file__)), "..", "examples"))


def _stub_sdk():
    sdk = types.ModuleType("claude_agent_sdk")

    class ClaudeAgentOptions:
        def __init__(self, **kwargs):
            self.kwargs = kwargs

    class ClaudeSDKClient:
        fail_resume = False
        instances = []

        def __init__(self, options):
            self.options = options
            self.connected = False
            self.sent = []
            ClaudeSDKClient.instances.append(self)

        async def connect(self):
            if ClaudeSDKClient.fail_resume and self.options.kwargs.get("resume"):
                raise RuntimeError("no such session")
            self.connected = True

        async def disconnect(self):
            self.connected = False

        async def query(self, prompt, session_id="default"):
            if isinstance(prompt, str):
                self.sent.append(prompt)
            else:
                async for m in prompt:
                    self.sent.append(m)

        async def receive_response(self):
            return
            yield  # pragma: no cover

    class HookMatcher:
        def __init__(self, matcher=None, hooks=None, timeout=None):
            self.matcher, self.hooks, self.timeout = matcher, hooks or [], timeout

    class ResultMessage:
        def __init__(self, **kw):
            self.__dict__.update(kw)

    class StreamEvent:
        pass

    def create_sdk_mcp_server(name, version="1.0.0", tools=None):
        return {"type": "sdk", "name": name, "tools": tools or []}

    def tool(name, description, schema):
        def deco(fn):
            return types.SimpleNamespace(name=name, description=description, handler=fn)
        return deco

    sdk.ClaudeAgentOptions = ClaudeAgentOptions
    sdk.ClaudeSDKClient = ClaudeSDKClient
    sdk.HookMatcher = HookMatcher
    sdk.ResultMessage = ResultMessage
    sdk.StreamEvent = StreamEvent
    sdk.create_sdk_mcp_server = create_sdk_mcp_server
    sdk.tool = tool
    return sdk


sys.modules.setdefault("claude_agent_sdk", _stub_sdk())
import petronilo_agent  # noqa: E402

SDK = sys.modules["claude_agent_sdk"]


class FakeVA:
    ACTION_MAP = {"sit": None, "stand": None}

    def __init__(self):
        self.context = "Hoy es lunes 21 de septiembre de 2026, 08:15. Pila: 7.80 V."

    def turn_context(self):
        return self.context


def make_brain(tmp, **kw):
    kw.setdefault("state_path", os.path.join(tmp, "agent_session.json"))
    brain = petronilo_agent.AgentBrain(api_key="k", workspace=tmp, **kw)
    brain.attach(FakeVA())
    return brain


def run(brain, coro):
    return asyncio.run_coroutine_threadsafe(coro, brain._loop).result(timeout=5)


class ResumeWindowTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        SDK.ClaudeSDKClient.fail_resume = False
        SDK.ClaudeSDKClient.instances.clear()

    def test_no_session_no_resume(self):
        brain = make_brain(self.tmp)
        self.assertIsNone(brain.resume_id())

    def test_resume_inside_window_only(self):
        brain = make_brain(self.tmp, resume_within=600)
        brain._remember_session("abc")
        ended = brain.last_session_end
        self.assertEqual(brain.resume_id(now=ended + 599), "abc")
        self.assertIsNone(brain.resume_id(now=ended + 600))

    def test_resume_disabled(self):
        brain = make_brain(self.tmp, resume_within=0)
        brain._remember_session("abc")
        self.assertIsNone(brain.resume_id())

    def test_state_file_round_trip(self):
        brain = make_brain(self.tmp, resume_within=3600)
        brain._remember_session("sess-1")
        path = os.path.join(self.tmp, "agent_session.json")
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        self.assertEqual(data["session_id"], "sess-1")
        again = make_brain(self.tmp, resume_within=3600)
        self.assertEqual(again.resume_id(), "sess-1")
        again._forget_session()
        third = make_brain(self.tmp, resume_within=3600)
        self.assertIsNone(third.resume_id())

    def test_corrupt_state_file_is_ignored(self):
        path = os.path.join(self.tmp, "agent_session.json")
        with open(path, "w", encoding="utf-8") as f:
            f.write("{not json")
        brain = make_brain(self.tmp)
        self.assertIsNone(brain.resume_id())

    def test_connect_resumes_then_remembers_on_disconnect(self):
        brain = make_brain(self.tmp, resume_within=3600)
        brain._remember_session("old")
        run(brain, brain._connect("prompt"))
        client = SDK.ClaudeSDKClient.instances[-1]
        self.assertEqual(client.options.kwargs["resume"], "old")
        self.assertIs(brain._client, client)
        # a result message names the (same) session; end() remembers it again
        brain._session_id = "old"
        brain.end()
        self.assertIsNone(brain._client)
        self.assertEqual(brain.resume_id(), "old")

    def test_stale_prewarmed_resume_is_recycled(self):
        # prewarmed right after the last conversation (inside the window), but
        # the next wake word comes after the window: start fresh instead
        brain = make_brain(self.tmp, resume_within=600)
        brain._remember_session("old")
        run(brain, brain._connect("prompt"))
        first = brain._client
        self.assertEqual(first.options.kwargs["resume"], "old")
        brain._resumed_end -= 601
        run(brain, brain._connect("prompt"))
        self.assertIsNot(brain._client, first)
        self.assertFalse(first.connected)
        self.assertNotIn("resume", brain._client.options.kwargs)
        self.assertIsNone(brain.resume_id())

    def test_fresh_prewarmed_resume_is_kept(self):
        brain = make_brain(self.tmp, resume_within=600)
        brain._remember_session("old")
        run(brain, brain._connect("prompt"))
        first = brain._client
        run(brain, brain._connect("prompt"))
        self.assertIs(brain._client, first)

    def test_failed_resume_falls_back_to_fresh_session(self):
        brain = make_brain(self.tmp, resume_within=3600)
        brain._remember_session("gone")
        SDK.ClaudeSDKClient.fail_resume = True
        run(brain, brain._connect("prompt"))
        self.assertIsNotNone(brain._client)
        self.assertNotIn("resume", brain._client.options.kwargs)
        self.assertIsNone(brain.resume_id())   # forgotten, not retried next time


class OptionsTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)

    def test_system_prompt_is_custom_without_snapshot(self):
        brain = make_brain(self.tmp)
        options, names = brain._options("SOUL")
        self.assertEqual(options.kwargs["system_prompt"],
                         {"type": "custom", "prompt": "SOUL", "snapshot": False})
        self.assertNotIn("resume", options.kwargs)
        self.assertNotIn("fallback_model", options.kwargs)
        self.assertEqual(names, set())

    def test_resume_and_fallback_passed_through(self):
        brain = make_brain(self.tmp, fallback_model="claude-sonnet-5")
        options, _ = brain._options("SOUL", resume="s1")
        self.assertEqual(options.kwargs["resume"], "s1")
        self.assertEqual(options.kwargs["fallback_model"], "claude-sonnet-5")

    def test_hooks_registered(self):
        brain = make_brain(self.tmp)
        options, _ = brain._options("SOUL")
        hooks = options.kwargs["hooks"]
        self.assertEqual(set(hooks), {"PreToolUse", "UserPromptSubmit", "PreCompact"})
        self.assertIn(brain._turn_context, hooks["UserPromptSubmit"][0].hooks)
        self.assertIs(options.kwargs["stderr"], brain._stderr)


class HookTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.brain = make_brain(self.tmp)

    def test_turn_context_shape(self):
        out = asyncio.run(self.brain._turn_context({"hook_event_name": "UserPromptSubmit"}, None, None))
        self.assertEqual(out, {"hookSpecificOutput": {
            "hookEventName": "UserPromptSubmit",
            "additionalContext": self.brain.va.context}})

    def test_turn_context_empty_when_nothing_to_add(self):
        self.brain.va.context = ""
        out = asyncio.run(self.brain._turn_context({}, None, None))
        self.assertEqual(out, {})

    def test_turn_context_swallows_errors(self):
        def boom():
            raise RuntimeError("sensor")
        self.brain.va.turn_context = boom
        out = asyncio.run(self.brain._turn_context({}, None, None))
        self.assertEqual(out, {})

    def test_precompact_returns_empty(self):
        out = asyncio.run(self.brain._on_compact({"trigger": "auto"}, None, None))
        self.assertEqual(out, {})


class ImageMessageTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.brain = make_brain(self.tmp)

    def test_user_message_with_image_then_text(self):
        block = {"type": "image", "source": {"type": "base64", "media_type": "image/jpeg", "data": "AAA="}}
        msg = petronilo_agent.AgentBrain.user_message("¿qué ves?", block)
        self.assertEqual(msg["type"], "user")
        self.assertEqual(msg["parent_tool_use_id"], None)
        self.assertEqual(msg["session_id"], "default")
        content = msg["message"]["content"]
        self.assertEqual(msg["message"]["role"], "user")
        self.assertEqual([b["type"] for b in content], ["image", "text"])
        self.assertEqual(content[1]["text"], "¿qué ves?")

    def test_user_message_plain(self):
        msg = petronilo_agent.AgentBrain.user_message("hola")
        self.assertEqual(msg["message"]["content"], "hola")

    def test_image_block_from_file(self):
        path = os.path.join(self.tmp, "img.jpeg")
        with open(path, "wb") as f:
            f.write(b"\xff\xd8jpeg")
        block = petronilo_agent.AgentBrain._image_block(path)
        self.assertEqual(block["source"]["media_type"], "image/jpeg")
        self.assertEqual(block["source"]["data"], "/9hqcGVn")

    def test_missing_image_falls_back_to_text(self):
        run(self.brain, self.brain._connect("prompt"))
        run(self.brain, self.brain._query("hola", os.path.join(self.tmp, "nope.jpeg")))
        self.assertEqual(self.brain._client.sent, ["hola"])

    def test_query_sends_one_message_with_image(self):
        path = os.path.join(self.tmp, "img.jpeg")
        with open(path, "wb") as f:
            f.write(b"x")
        run(self.brain, self.brain._connect("prompt"))
        run(self.brain, self.brain._query("¿quién está?", path))
        sent = self.brain._client.sent
        self.assertEqual(len(sent), 1)
        self.assertEqual([b["type"] for b in sent[0]["message"]["content"]], ["image", "text"])


class CostTests(unittest.TestCase):
    """ClaudeSDKClient is streaming input mode: ResultMessage.total_cost_usd is
    the connection's running total, so only the increase counts."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.brain = make_brain(self.tmp)

    def test_running_total_counted_once(self):
        self.assertAlmostEqual(self.brain._add_cost(0.10), 0.10)
        self.assertAlmostEqual(self.brain._add_cost(0.25), 0.15)
        self.assertAlmostEqual(self.brain._add_cost(0.25), 0.0)
        self.assertAlmostEqual(self.brain.spent_today, 0.25)

    def test_reset_starts_over(self):
        self.brain._add_cost(0.30)
        # a new connection (or /clear) reports from zero again
        self.assertAlmostEqual(self.brain._add_cost(0.05), 0.05)
        self.assertAlmostEqual(self.brain.spent_today, 0.35)

    def test_disconnect_resets_session_total(self):
        run(self.brain, self.brain._connect("prompt"))
        self.brain._add_cost(0.20)
        self.brain.end()
        self.assertEqual(self.brain._session_cost, 0.0)
        self.assertAlmostEqual(self.brain._add_cost(0.10), 0.10)
        self.assertAlmostEqual(self.brain.spent_today, 0.30)


if __name__ == "__main__":
    unittest.main()
