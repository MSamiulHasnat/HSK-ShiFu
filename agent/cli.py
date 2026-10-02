"""
Standalone CLI for the HSK knowledge agent.

Usage:
    python -m agent.cli "What does 把字句 mean?"
    python -m agent.cli --dfs "How does X connect to Y?"

Works with no LLM provider configured (shows the raw retrieved graph
context); set HSK_AGENT_PROVIDER (see agent/providers.py) to get a
synthesized, cited answer instead.
"""

from __future__ import annotations

import argparse
import sys

from agent import prompts, retrieval, teacher
from agent.providers import get_provider


def answer(
    question: str,
    *,
    dfs: bool = False,
    budget: int = 2000,
    provider_name: str | None = None,
    mode: str = "answer",
) -> str:
    if mode == "teach":
        try:
            return teacher.teach(question, provider_name=provider_name, dfs=dfs).answer
        except RuntimeError as e:
            return f"Error: {e}"

    result = retrieval.query(question, dfs=dfs, budget=budget)

    if result.error:
        return f"Error: {result.error}"

    if not result.found:
        return prompts.NOT_FOUND_MESSAGE

    provider = get_provider(provider_name)
    if provider is None:
        lines = [
            "(No LLM provider configured -- showing raw retrieved graph context.",
            " Set HSK_AGENT_PROVIDER once a provider is implemented in agent/providers.py",
            " to get a synthesized, cited answer instead.)",
            "",
            result.raw_output.strip(),
        ]
        return "\n".join(lines)

    user_message = prompts.build_user_message(question, result.raw_output)
    return provider.complete(prompts.SYSTEM_PROMPT, user_message)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Query the HSK knowledge graph.")
    parser.add_argument("question", help="Your HSK question")
    parser.add_argument("--dfs", action="store_true", help="Use depth-first traversal (trace a specific chain)")
    parser.add_argument("--budget", type=int, default=2000, help="Token budget for graph context (default 2000)")
    parser.add_argument("--provider", default=None, help="Override HSK_AGENT_PROVIDER env var")
    parser.add_argument("--teach", action="store_true", help="Teacher mode: a structured lesson with practice questions")
    args = parser.parse_args(argv)

    mode = "teach" if args.teach else "answer"
    print(answer(args.question, dfs=args.dfs, budget=args.budget, provider_name=args.provider, mode=mode))
    return 0


if __name__ == "__main__":
    sys.exit(main())
