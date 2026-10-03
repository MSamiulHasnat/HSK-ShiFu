"""
Pluggable LLM provider interface for the standalone API/server path.

The CLI and server import `get_provider()` below and work fine with it
returning None (they just show the raw graph context and skip synthesis) if
none is configured. To add another provider, subclass `Provider` and
register it in `PROVIDERS`; nothing else in `agent/` needs to change.

This only matters for the standalone CLI/server. Claude Code, Antigravity,
and Codex never go through this file -- they ARE the LLM, synthesizing
answers themselves from `agent.retrieval` / `graphify query` output per the
instructions in CLAUDE.md / AGENTS.md / GEMINI.md.
"""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from abc import ABC, abstractmethod


class Provider(ABC):
    """A synthesis backend: takes a system prompt + user message, returns text."""

    name: str
    # Set by chat() when the backend returned a separate reasoning/thinking
    # trace alongside the answer (e.g. llama-server with reasoning enabled).
    # None for providers that don't support it, or when it wasn't requested.
    last_reasoning: str | None = None

    @abstractmethod
    def chat(self, system_prompt: str, messages: list[dict]) -> str:
        """Multi-turn: messages are [{"role": "user"|"assistant", "content": str}, ...]."""
        raise NotImplementedError

    def complete(self, system_prompt: str, user_message: str) -> str:
        return self.chat(system_prompt, [{"role": "user", "content": user_message}])


class OllamaProvider(Provider):
    """
    Local, no-API-key provider backed by a running Ollama server
    (https://ollama.com). Uses Ollama's native /api/chat endpoint via
    stdlib urllib, so no extra dependency is needed.

    Requires `ollama serve` running (the desktop app runs this for you) and
    the model pulled first: `ollama pull <model>`.
    """

    name = "ollama"

    def __init__(self, model: str | None = None, base_url: str | None = None, timeout: int = 300):
        self.model = model or os.environ.get("OLLAMA_MODEL", "gemma3n:e4b")
        self.base_url = (base_url or os.environ.get("OLLAMA_BASE_URL", "http://localhost:11434")).rstrip("/")
        self.timeout = timeout
        # Ollama's default context is ~2K tokens and it silently truncates the
        # prompt from the front -- which drops the system prompt (all the
        # grounding rules) first. Textbook pages + graph context need far more.
        self.num_ctx = int(os.environ.get("OLLAMA_NUM_CTX", "16384"))

    def chat(self, system_prompt: str, messages: list[dict]) -> str:
        payload = {
            "model": self.model,
            "messages": [{"role": "system", "content": system_prompt}, *messages],
            "stream": False,
            "options": {"temperature": 0.2, "num_ctx": self.num_ctx},
        }
        req = urllib.request.Request(
            f"{self.base_url}/api/chat",
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                data = json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            # Reached the server, but it returned an error status (e.g. 404 for
            # an unpulled model) -- the body is still the JSON {"error": ...}.
            try:
                body = json.loads(e.read().decode("utf-8"))
                detail = body.get("error", str(e))
            except (json.JSONDecodeError, UnicodeDecodeError):
                detail = str(e)
            raise RuntimeError(
                f"Ollama error for model {self.model!r}: {detail} "
                f"(pull it first: `ollama pull {self.model}`)"
            ) from e
        except urllib.error.URLError as e:
            raise RuntimeError(
                f"Could not reach Ollama at {self.base_url} (is `ollama serve` running?): {e}"
            ) from e
        except TimeoutError as e:
            raise RuntimeError(f"Ollama request timed out after {self.timeout}s (model: {self.model}).") from e

        if "error" in data:
            raise RuntimeError(
                f"Ollama error for model {self.model!r}: {data['error']} "
                f"(pull it first: `ollama pull {self.model}`)"
            )
        return data["message"]["content"]


class LlamaCppProvider(Provider):
    """
    A local `llama-server` (llama.cpp, or a fork such as PrismML's for the
    ternary Bonsai models) via its OpenAI-compatible /v1/chat/completions API.

    Defaults follow the Ternary Bonsai 2 model card's *instruct* settings,
    with reasoning switched off (`reasoning_effort: "none"`) -- a chat tutor
    wants a direct reply, not a long thinking trace first. Override with
    LLAMACPP_REASONING=medium (or xhigh) to let the model think.
    """

    name = "llamacpp"

    def __init__(self, base_url: str | None = None, timeout: int = 900):
        self.base_url = (base_url or os.environ.get("LLAMACPP_BASE_URL", "http://localhost:8080")).rstrip("/")
        self.timeout = timeout
        self.reasoning = os.environ.get("LLAMACPP_REASONING", "none")
        self.max_tokens = int(os.environ.get("LLAMACPP_MAX_TOKENS", "2048" if self.reasoning == "none" else "16384"))

    def chat(self, system_prompt: str, messages: list[dict]) -> str:
        payload = {
            "messages": [{"role": "system", "content": system_prompt}, *messages],
            "temperature": 0.7,
            "top_p": 0.8,
            "top_k": 20,
            "min_p": 0.0,
            "max_tokens": self.max_tokens,
            "reasoning_effort": self.reasoning,
        }
        req = urllib.request.Request(
            f"{self.base_url}/v1/chat/completions",
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                data = json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            detail = e.read().decode("utf-8", errors="replace")[:500]
            raise RuntimeError(f"llama-server error {e.code}: {detail}") from e
        except urllib.error.URLError as e:
            raise RuntimeError(
                f"Could not reach llama-server at {self.base_url} (is it running?): {e}"
            ) from e
        except TimeoutError as e:
            raise RuntimeError(f"llama-server timed out after {self.timeout}s.") from e

        message = data["choices"][0]["message"]
        self.last_reasoning = message.get("reasoning_content") or None
        content = message.get("content") or ""
        if not content.strip():
            raise RuntimeError("llama-server returned an empty reply (output limit hit during reasoning?).")
        return content


class AnthropicProvider(Provider):
    """
    Claude via the Anthropic API (api.anthropic.com) -- a paid API key,
    separate from a claude.ai subscription. Get one at console.anthropic.com
    and set ANTHROPIC_API_KEY.

    Defaults to Sonnet 5.5 with its own adaptive thinking left on (omitting
    `thinking` runs it at the model's default effort). Don't add a
    `temperature` override here: with thinking on, a non-default sampling
    param is a 400 on this model.
    """

    name = "anthropic"

    def __init__(self, model: str | None = None, api_key: str | None = None):
        from anthropic import Anthropic

        self.client = Anthropic(api_key=api_key)  # reads ANTHROPIC_API_KEY if None
        self.model = model or os.environ.get("ANTHROPIC_MODEL", "claude-sonnet-5-5")
        self.max_tokens = int(os.environ.get("ANTHROPIC_MAX_TOKENS", "4096"))
        self.effort = os.environ.get("ANTHROPIC_EFFORT")  # low|medium|high|xhigh|max; unset = model default

    def chat(self, system_prompt: str, messages: list[dict]) -> str:
        import anthropic

        kwargs = dict(model=self.model, max_tokens=self.max_tokens, system=system_prompt, messages=messages)
        if self.effort:
            kwargs["output_config"] = {"effort": self.effort}

        try:
            resp = self.client.messages.create(**kwargs)
        except TypeError as e:
            # No credential configured at all -- the SDK validates this client-side
            # before any request goes out, so it raises TypeError, not AuthenticationError.
            raise RuntimeError("No Anthropic API key configured -- set ANTHROPIC_API_KEY.") from e
        except anthropic.AuthenticationError as e:
            raise RuntimeError("Anthropic API key invalid -- check ANTHROPIC_API_KEY.") from e
        except anthropic.RateLimitError as e:
            raise RuntimeError(f"Anthropic rate limit hit: {e.message}") from e
        except anthropic.APIStatusError as e:
            raise RuntimeError(f"Anthropic API error {e.status_code}: {e.message}") from e
        except anthropic.APIConnectionError as e:
            raise RuntimeError(f"Could not reach the Anthropic API: {e}") from e

        if resp.stop_reason == "refusal" and resp.stop_details:
            raise RuntimeError(f"Claude declined to answer ({resp.stop_details.category}).")

        text = "".join(b.text for b in resp.content if b.type == "text")
        if not text.strip():
            raise RuntimeError("Anthropic API returned an empty reply.")
        return text


PROVIDERS: dict[str, type[Provider]] = {
    "ollama": OllamaProvider,
    "llamacpp": LlamaCppProvider,
    "anthropic": AnthropicProvider,
    # "openai": OpenAIProvider,
    # "gemini": GeminiProvider,
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
