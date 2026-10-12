"""Shared test helpers: throwaway databases and a scripted stand-in LLM provider."""

from __future__ import annotations

import pathlib
import tempfile

from agent import chat_store, progress, providers


def use_temp_databases() -> pathlib.Path:
    """Point chat history and the learning record at a fresh temp directory."""
    tmp = pathlib.Path(tempfile.mkdtemp(prefix="hsk-test-"))
    chat_store.DB_PATH = tmp / "chat_sessions.db"
    progress.DB_PATH = tmp / "progress.db"
    return tmp


class ScriptedProvider(providers.Provider):
    """Replies with canned text and records every request it was given."""

    name = "scripted"

    def __init__(self, replies: list[str] | None = None, fail: str | None = None):
        self.replies = list(replies or ["好的。 Let's start."])
        self.fail = fail
        self.requests: list[tuple[str, list[dict]]] = []

    def chat(self, system_prompt: str, messages: list[dict]) -> str:
        self.requests.append((system_prompt, [dict(m) for m in messages]))
        if self.fail:
            raise RuntimeError(self.fail)
        return self.replies.pop(0) if len(self.replies) > 1 else self.replies[0]


def install_provider(provider: providers.Provider) -> str:
    providers.PROVIDERS[provider.name] = lambda: provider
    return provider.name
