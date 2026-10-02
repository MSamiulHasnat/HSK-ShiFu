"""
Pluggable LLM provider interface for the standalone API/server path.

No provider is implemented yet -- the CLI and server import `get_provider()`
below and work fine with it returning None (they just show the raw graph
context and skip synthesis). When a provider is chosen, implement it here by
subclassing `Provider` and registering it in `PROVIDERS`; nothing else in
`agent/` needs to change.

This only matters for the standalone CLI/server. Claude Code, Antigravity,
and Codex never go through this file -- they ARE the LLM, synthesizing
answers themselves from `agent.retrieval` / `graphify query` output per the
instructions in CLAUDE.md / AGENTS.md / GEMINI.md.
"""

from __future__ import annotations

import os
from abc import ABC, abstractmethod


class Provider(ABC):
    """A synthesis backend: takes a system prompt + user message, returns text."""

    name: str

    @abstractmethod
    def complete(self, system_prompt: str, user_message: str) -> str:
        raise NotImplementedError


# Example of what a real provider looks like, for whenever one is chosen:
#
#   class AnthropicProvider(Provider):
#       name = "anthropic"
#
#       def __init__(self, model: str = "claude-sonnet-5", api_key: str | None = None):
#           from anthropic import Anthropic
#           self.client = Anthropic(api_key=api_key)  # reads ANTHROPIC_API_KEY if None
#           self.model = model
#
#       def complete(self, system_prompt: str, user_message: str) -> str:
#           resp = self.client.messages.create(
#               model=self.model,
#               max_tokens=1000,
#               temperature=0.2,
#               system=system_prompt,
#               messages=[{"role": "user", "content": user_message}],
#           )
#           return resp.content[0].text
#
# Then register it below: PROVIDERS["anthropic"] = AnthropicProvider

PROVIDERS: dict[str, type[Provider]] = {
    # "anthropic": AnthropicProvider,
    # "openai": OpenAIProvider,
    # "gemini": GeminiProvider,
    # "ollama": OllamaProvider,
}


def get_provider(name: str | None = None) -> Provider | None:
    """
    Return a configured provider instance, or None if none is set up.

    Selection: explicit `name` arg, else HSK_AGENT_PROVIDER env var, else None
    (no provider configured -- callers should handle this by returning the
    raw retrieved graph context instead of a synthesized answer).
    """
    name = name or os.environ.get("HSK_AGENT_PROVIDER")
    if not name:
        return None
    provider_cls = PROVIDERS.get(name)
    if provider_cls is None:
        available = ", ".join(PROVIDERS) or "(none registered yet)"
        raise ValueError(f"Unknown provider {name!r}. Available: {available}")
    return provider_cls()
