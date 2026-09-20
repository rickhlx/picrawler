"""memory_extractor.AgentExtractor without the real claude-agent-sdk: the
module's `query`, `ClaudeAgentOptions` and `ResultMessage` are patched per
test, so this works whether or not another test already put a stub
`claude_agent_sdk` in sys.modules."""
import json
import os
import sys
import types
import unittest
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(os.path.realpath(__file__)), "..", "examples"))

def _ensure_stub():
    """Another test (test_agent_brain) may already have stubbed the SDK without
    the names this module imports; add whatever is missing. If nothing is
    there and the SDK is not installed, install a throwaway stub just for the
    import below (removed again in _drop_stub, so a later test's own stub,
    installed with setdefault, is not shadowed by this partial one)."""
    global _temporary
    sdk = sys.modules.get("claude_agent_sdk")
    try:
        if sdk is None:
            import claude_agent_sdk as sdk  # noqa: F811 - real SDK if installed
    except ImportError:
        sdk = types.ModuleType("claude_agent_sdk")
        sys.modules["claude_agent_sdk"] = sdk
        _temporary = True

    class _Options:
        def __init__(self, **kwargs):
            self.kwargs = kwargs

    class _Result:
        def __init__(self, **kw):
            self.__dict__.update(kw)

    async def _query(*, prompt, options=None, transport=None):
        return
        yield  # pragma: no cover

    for name, value in (("ClaudeAgentOptions", _Options), ("ResultMessage", _Result), ("query", _query)):
        if not hasattr(sdk, name):
            setattr(sdk, name, value)


_temporary = False
_ensure_stub()

import memory_extractor  # noqa: E402

if _temporary:
    del sys.modules["claude_agent_sdk"]


class FakeOptions:
    def __init__(self, **kwargs):
        self.kwargs = kwargs


class FakeResult:
    def __init__(self, **kw):
        self.__dict__.update(kw)


def fake_query(*results, record=None):
    async def query(*, prompt, options=None, transport=None):
        if record is not None:
            record.append((prompt, options))
        for r in results:
            yield r
    return query


EDITS = {"add": [{"file": "user", "text": "Ricardo cumple el 3 de mayo"}],
         "update": [], "delete": [], "summary": "cumpleaños"}


class AgentExtractorTests(unittest.TestCase):
    def setUp(self):
        self.calls = []
        self.p_opts = mock.patch.object(memory_extractor, "ClaudeAgentOptions", FakeOptions)
        self.p_res = mock.patch.object(memory_extractor, "ResultMessage", FakeResult)
        self.p_opts.start()
        self.p_res.start()
        self.addCleanup(self.p_opts.stop)
        self.addCleanup(self.p_res.stop)

    def _extractor(self, results, **kw):
        q = fake_query(*results, record=self.calls)
        mock.patch.object(memory_extractor, "query", q).start()
        self.addCleanup(mock.patch.stopall)
        return memory_extractor.AgentExtractor(api_key="k", workspace="/ws", **kw)

    def test_options(self):
        ext = self._extractor([FakeResult(structured_output=EDITS, total_cost_usd=0.001)],
                              user="petronilo", model="claude-haiku-4-5")
        ext.extract_json("SYSTEM", "USER")
        prompt, options = self.calls[0]
        self.assertEqual(prompt, "USER")
        kw = options.kwargs
        self.assertEqual(kw["system_prompt"], "SYSTEM")
        self.assertEqual(kw["model"], "claude-haiku-4-5")
        self.assertEqual(kw["tools"], [])
        self.assertEqual(kw["mcp_servers"], {})
        self.assertTrue(kw["strict_mcp_config"])
        self.assertEqual(kw["setting_sources"], [])
        self.assertEqual(kw["permission_mode"], "dontAsk")
        self.assertEqual(kw["max_turns"], 3)
        self.assertEqual(kw["cwd"], "/ws")
        self.assertEqual(kw["user"], "petronilo")
        self.assertEqual(kw["env"]["ANTHROPIC_API_KEY"], "k")
        self.assertEqual(kw["env"]["HOME"], os.path.expanduser("~petronilo"))
        self.assertEqual(kw["output_format"]["type"], "json_schema")
        schema = kw["output_format"]["schema"]
        self.assertEqual(schema, memory_extractor.SCHEMA)
        self.assertEqual(set(schema["required"]), {"add", "update", "delete", "summary"})
        self.assertFalse(schema["additionalProperties"])

    def test_no_user_no_home_override(self):
        ext = self._extractor([FakeResult(structured_output=EDITS)])
        ext.extract_json("S", "U")
        self.assertNotIn("HOME", self.calls[0][1].kwargs["env"])

    def test_structured_output_returned(self):
        ext = self._extractor([FakeResult(structured_output=EDITS, total_cost_usd=0.002)])
        self.assertEqual(ext.extract_json("S", "U"), EDITS)

    def test_result_json_string_fallback(self):
        ext = self._extractor([FakeResult(structured_output=None, result="```json\n" + json.dumps(EDITS) + "\n```")])
        self.assertEqual(ext.extract_json("S", "U"), EDITS)

    def test_error_result_raises(self):
        ext = self._extractor([FakeResult(structured_output=None, result="", subtype="error_max_turns",
                                          errors=["ran out of turns"], is_error=True)])
        with self.assertRaises(RuntimeError) as cm:
            ext.extract_json("S", "U")
        self.assertIn("error_max_turns", str(cm.exception))
        self.assertIn("ran out of turns", str(cm.exception))

    def test_no_result_raises(self):
        ext = self._extractor([])
        with self.assertRaises(RuntimeError):
            ext.extract_json("S", "U")

    def test_on_cost_called(self):
        costs = []
        ext = self._extractor([FakeResult(structured_output=EDITS, total_cost_usd=0.0042)], on_cost=costs.append)
        ext.extract_json("S", "U")
        self.assertEqual(costs, [0.0042])

    def test_on_cost_skipped_when_zero_or_missing(self):
        costs = []
        ext = self._extractor([FakeResult(structured_output=EDITS, total_cost_usd=None)], on_cost=costs.append)
        ext.extract_json("S", "U")
        self.assertEqual(costs, [])

    def test_on_cost_failure_does_not_break_extraction(self):
        def boom(c):
            raise RuntimeError("no")
        ext = self._extractor([FakeResult(structured_output=EDITS, total_cost_usd=0.01)], on_cost=boom)
        self.assertEqual(ext.extract_json("S", "U"), EDITS)

    def test_only_last_result_counts_and_other_messages_ignored(self):
        ext = self._extractor([types.SimpleNamespace(kind="assistant"),
                               FakeResult(structured_output=EDITS, total_cost_usd=0.001)])
        self.assertEqual(ext.extract_json("S", "U"), EDITS)

    def test_works_inside_a_running_loop(self):
        import asyncio
        ext = self._extractor([FakeResult(structured_output=EDITS)])

        async def main():
            return ext.extract_json("S", "U")

        self.assertEqual(asyncio.run(main()), EDITS)


if __name__ == "__main__":
    unittest.main()
