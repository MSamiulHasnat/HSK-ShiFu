"""The token-cheap lookups for AI assistants (agent/ask.py) and their MCP server."""

import json
import subprocess
import sys
import unittest

from agent import ask, mcp_server
from agent.retrieval import PROJECT_ROOT


class Lookups(unittest.TestCase):
    def test_word_entry_is_cited_and_small(self):
        out = ask.word("已经")
        self.assertTrue(out.startswith("已经 (yǐjīng) adv. already — HSK 2, Lesson 4 (HSK Level 2, page 47)"))
        self.assertLess(len(out), 1500)

    def test_context_includes_the_grammar_explanation(self):
        out = ask.context("What's the difference between 还是 and 或者?")
        self.assertIn("(HSK Level 3, page 39)", out)
        self.assertIn("疑问句", out)  # the book's own explanation text
        self.assertLessEqual(len(out), ask.MAX_CONTEXT + 80)

    def test_lesson_reference(self):
        self.assertTrue(ask.context("teach me HSK 3 lesson 11").startswith("HSK 3 Lesson 11: 别忘了把空调关了"))

    def test_not_covered(self):
        self.assertIn(ask.NOT_FOUND, ask.context("what is quantum physics"))

    def test_check(self):
        self.assertIn("NOT in the textbook", ask.check("我已经回家了。(Wǒ yǐjīng huí jiā le.)"))
        self.assertIn("(HSK Level 2, page 49)", ask.check("王老师已经回家了。(Wáng lǎoshī yǐjīng huí jiā le.)"))


class McpServer(unittest.TestCase):
    def test_protocol_round_trip(self):
        init = mcp_server.handle({"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {"protocolVersion": "2025-06-18"}})
        self.assertEqual(init["result"]["protocolVersion"], "2025-06-18")
        self.assertIsNone(mcp_server.handle({"jsonrpc": "2.0", "method": "notifications/initialized"}))
        names = [t["name"] for t in mcp_server.handle({"jsonrpc": "2.0", "id": 2, "method": "tools/list"})["result"]["tools"]]
        self.assertIn("hsk_context", names)
        call = mcp_server.handle({"jsonrpc": "2.0", "id": 3, "method": "tools/call",
                                  "params": {"name": "hsk_lesson", "arguments": {"level": 2, "lesson": 4}}})
        self.assertFalse(call["result"]["isError"])
        self.assertIn("这个工作是他帮我介绍的", call["result"]["content"][0]["text"])
        bad = mcp_server.handle({"jsonrpc": "2.0", "id": 4, "method": "tools/call", "params": {"name": "nope"}})
        self.assertIn("error", bad)

    def test_stdio_process(self):
        lines = [{"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}},
                 {"jsonrpc": "2.0", "id": 2, "method": "tools/call", "params": {"name": "hsk_word", "arguments": {"query": "伞"}}}]
        proc = subprocess.run([sys.executable, "-m", "agent.mcp_server"], cwd=PROJECT_ROOT, capture_output=True,
                              input="\n".join(json.dumps(l) for l in lines) + "\n", encoding="utf-8", timeout=60)
        replies = [json.loads(l) for l in proc.stdout.splitlines()]
        self.assertEqual([r["id"] for r in replies], [1, 2])
        self.assertIn("伞 (sǎn) n. umbrella", replies[1]["result"]["content"][0]["text"])


if __name__ == "__main__":
    unittest.main()
