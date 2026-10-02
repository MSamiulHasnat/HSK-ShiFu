"""
Graph-grounded retrieval for the HSK knowledge agent.

This module's only job is pulling facts out of the graphify knowledge graph
(graphify-out/graph.json) -- it never talks to an LLM. It shells out to the
`graphify` CLI (the same tool Claude Code / Antigravity / Codex use via their
installed graphify skill), so there is exactly one retrieval implementation
shared by every integration path: the coding-agent skills, the standalone
CLI, and the web server.
"""

from __future__ import annotations

import re
import subprocess
from dataclasses import dataclass, field
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
GRAPH_PATH = PROJECT_ROOT / "graphify-out" / "graph.json"

NODE_LINE_RE = re.compile(
    r"^NODE (?P<label>.+?) \[src=(?P<src>.*?) loc=(?P<loc>.*?) community=(?P<community>.*)\]$"
)
HEADER_RE = re.compile(r"\| (?P<n>\d+) nodes found")
TRUNCATED_RE = re.compile(r"showing (?P<shown>\d+) of (?P<total>\d+) nodes")
NO_MATCH_RE = re.compile(r"No matching nodes found")


@dataclass
class GraphNode:
    label: str
    source_file: str
    source_location: str | None
    community: str


@dataclass
class RetrievalResult:
    question: str
    found: bool
    nodes: list[GraphNode] = field(default_factory=list)
    raw_output: str = ""
    truncated: bool = False
    shown_count: int = 0
    total_count: int = 0
    error: str | None = None

    def citation_for(self, node: GraphNode) -> str:
        """Render a reader-friendly citation like '(HSK Level 3, page 107)'."""
        m = re.search(r"level([123]).*?page_(\d+)", node.source_file.replace("\\", "/"))
        if m:
            return f"(HSK Level {m.group(1)}, page {int(m.group(2))})"
        return f"({node.source_file})"


def graph_exists() -> bool:
    return GRAPH_PATH.exists()


def query(question: str, *, dfs: bool = False, budget: int = 2000) -> RetrievalResult:
    """
    Run `graphify query` against the built HSK knowledge graph and parse the
    result. This is the ONLY source of facts for the agent -- callers must
    never supplement it with outside knowledge.

    Note: this does not perform graphify's recommended vocabulary-expansion
    step (see .claude/skills/graphify/references/query.md Step 0), which
    needs an LLM to map the user's wording onto the graph's actual label
    vocabulary. A host agent with its own LLM (Claude Code, Antigravity,
    Codex) should do that expansion itself before calling this, or before
    running `graphify query` directly. The standalone CLI/server fall back to
    passing the raw question straight through, which works for most queries
    since HSK node labels are already bilingual (hanzi + pinyin + English).
    """
    if not graph_exists():
        return RetrievalResult(
            question=question,
            found=False,
            error=(
                "No knowledge graph found at graphify-out/graph.json. "
                "Run the graphify build first (see INGESTION_REPORT.md)."
            ),
        )

    args = ["graphify", "query", question, "--budget", str(budget)]
    if dfs:
        args.append("--dfs")

    try:
        proc = subprocess.run(
            args,
            cwd=PROJECT_ROOT,
            capture_output=True,
            text=True,
            encoding="utf-8",
            timeout=60,
        )
    except FileNotFoundError:
        return RetrievalResult(
            question=question,
            found=False,
            error="`graphify` CLI not found on PATH. Install it with: pip install graphifyy",
        )
    except subprocess.TimeoutExpired:
        return RetrievalResult(question=question, found=False, error="graphify query timed out.")

    output = proc.stdout or proc.stderr or ""

    if NO_MATCH_RE.search(output):
        return RetrievalResult(question=question, found=False, raw_output=output)

    nodes: list[GraphNode] = []
    for line in output.splitlines():
        m = NODE_LINE_RE.match(line.strip())
        if m:
            loc = m.group("loc")
            nodes.append(
                GraphNode(
                    label=m.group("label"),
                    source_file=m.group("src"),
                    source_location=None if loc in ("None", "", "null") else loc,
                    community=m.group("community"),
                )
            )

    trunc_m = TRUNCATED_RE.search(output)
    shown = int(trunc_m.group("shown")) if trunc_m else len(nodes)
    total_m = HEADER_RE.search(output)
    total = int(total_m.group("n")) if total_m else len(nodes)

    return RetrievalResult(
        question=question,
        found=bool(nodes),
        nodes=nodes,
        raw_output=output,
        truncated=trunc_m is not None,
        shown_count=shown,
        total_count=total,
    )


def explain(node_name: str) -> RetrievalResult:
    """Run `graphify explain` for a plain-language single-node lookup."""
    if not graph_exists():
        return RetrievalResult(question=node_name, found=False, error="No knowledge graph found.")
    try:
        proc = subprocess.run(
            ["graphify", "explain", node_name],
            cwd=PROJECT_ROOT,
            capture_output=True,
            text=True,
            encoding="utf-8",
            timeout=60,
        )
    except FileNotFoundError:
        return RetrievalResult(question=node_name, found=False, error="`graphify` CLI not found on PATH.")
    output = proc.stdout or proc.stderr or ""
    found = not output.lower().startswith("no node matching")
    return RetrievalResult(question=node_name, found=found, raw_output=output)
