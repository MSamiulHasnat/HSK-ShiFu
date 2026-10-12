"""
MCP server exposing the textbook lookups in agent/ask.py as tools, so AI
assistants (Claude Code, Codex, GitHub Copilot in VS Code, Kimi, ...) can
answer HSK questions with a few hundred tokens of cited book content instead
of reading the repository.

Run:  python -m agent.mcp_server      (stdio; registered in .mcp.json, .vscode/mcp.json)

A minimal, dependency-free implementation of MCP's stdio transport:
newline-delimited JSON-RPC 2.0 with initialize, tools/list and tools/call.
"""

from __future__ import annotations

import json
import sys

from agent import ask

PROTOCOL_VERSION = "2025-06-18"

_TEXT = {"type": "string"}
_LEVEL = {"type": "integer", "minimum": 1, "maximum": 3}


def _tool(name: str, description: str, properties: dict, fn) -> dict:
    return {"name": name, "description": description, "fn": fn,
            "inputSchema": {"type": "object", "properties": properties, "required": list(properties),
                            "additionalProperties": False}}


TOOLS = [
    _tool("hsk_context", "Start here. Everything the HSK Standard Course textbooks (Levels 1-3) say that's needed to "
          "answer one question: word entries, grammar explanations, or a lesson summary ('HSK 2 lesson 4'), all with "
          "page citations. Include the Chinese term in the question.",
          {"question": _TEXT}, lambda a: ask.context(a["question"])),
    _tool("hsk_word", "A word's exact textbook entry (pinyin, part of speech, meaning, level, lesson, page) and "
          "textbook sentences that use it. Accepts hanzi, pinyin or English.",
          {"query": _TEXT}, lambda a: ask.word(a["query"])),
    _tool("hsk_search", "Search the textbooks' word lists by hanzi, pinyin (tones optional) or English.",
          {"query": _TEXT}, lambda a: ask.search(a["query"])),
    _tool("hsk_grammar", "Textbook grammar points whose title contains a term (e.g. 把, 了, 还是), with the book's "
          "explanation and examples.", {"term": _TEXT}, lambda a: ask.grammar(a["term"])),
    _tool("hsk_lesson", "A lesson's title, pages, word list and grammar points.",
          {"level": _LEVEL, "lesson": {"type": "integer", "minimum": 1, "maximum": 20}},
          lambda a: ask.lesson(a["level"], a["lesson"])),
    _tool("hsk_page", "The full transcription of one textbook page (PDF page number, as in citations).",
          {"level": _LEVEL, "page": {"type": "integer", "minimum": 1, "maximum": 210}},
          lambda a: ask.page(a["level"], a["page"])),
    _tool("hsk_check", "Check a draft answer: which 汉字 (pinyin) example sentences in it are printed in the "
          "textbooks, and which must be labelled as your own.", {"text": _TEXT}, lambda a: ask.check(a["text"])),
]
_BY_NAME = {t["name"]: t for t in TOOLS}


def handle(msg: dict) -> dict | None:
    """One JSON-RPC message in, one response out (None for notifications)."""
    method, mid = msg.get("method"), msg.get("id")
    if mid is None:
        return None  # notifications (e.g. notifications/initialized) need no reply
    if method == "initialize":
        version = (msg.get("params") or {}).get("protocolVersion") or PROTOCOL_VERSION
        result = {"protocolVersion": version, "capabilities": {"tools": {}},
                  "serverInfo": {"name": "hsk-shifu", "version": "1.0.0"},
                  "instructions": "Answer HSK questions only from these tools' output and keep the (HSK Level N, "
                                  "page N) citations. Don't read the repository's data files."}
    elif method == "ping":
        result = {}
    elif method == "tools/list":
        result = {"tools": [{k: v for k, v in t.items() if k != "fn"} for t in TOOLS]}
    elif method == "tools/call":
        params = msg.get("params") or {}
        tool = _BY_NAME.get(params.get("name"))
        if tool is None:
            return {"jsonrpc": "2.0", "id": mid, "error": {"code": -32602, "message": f"Unknown tool {params.get('name')!r}"}}
        try:
            text, is_error = tool["fn"](params.get("arguments") or {}), False
        except (KeyError, TypeError, ValueError) as e:
            text, is_error = f"Bad arguments: {e}", True
        result = {"content": [{"type": "text", "text": text}], "isError": is_error}
    else:
        return {"jsonrpc": "2.0", "id": mid, "error": {"code": -32601, "message": f"Method not found: {method}"}}
    return {"jsonrpc": "2.0", "id": mid, "result": result}


def main() -> None:
    stdin = open(sys.stdin.fileno(), encoding="utf-8", closefd=False)
    stdout = open(sys.stdout.fileno(), "w", encoding="utf-8", newline="\n", closefd=False)
    for line in stdin:
        if not line.strip():
            continue
        try:
            reply = handle(json.loads(line))
        except json.JSONDecodeError:
            reply = {"jsonrpc": "2.0", "id": None, "error": {"code": -32700, "message": "Parse error"}}
        if reply is not None:
            stdout.write(json.dumps(reply, ensure_ascii=False) + "\n")
            stdout.flush()


if __name__ == "__main__":
    main()
