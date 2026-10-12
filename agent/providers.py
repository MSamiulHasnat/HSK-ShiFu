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
from collections.abc import Iterator


class Provider(ABC):
    """A synthesis backend: takes a system prompt + user message, returns text."""

    name: str
    # Set by chat()/stream() when the backend returned a separate reasoning/thinking
    # trace alongside the answer (e.g. llama-server with reasoning enabled).
    # None for providers that don't support it, or when it wasn't requested.
    last_reasoning: str | None = None

    @abstractmethod
    def chat(self, system_prompt: str, messages: list[dict]) -> str:
        """Multi-turn: messages are [{"role": "user"|"assistant", "content": str}, ...]."""
        raise NotImplementedError

    def stream(self, system_prompt: str, messages: list[dict]) -> Iterator[tuple[str, str]]:
        """
        Like chat(), but yields ("text" | "thinking", chunk) pieces as they're
        generated. Providers without native streaming yield the whole reply once.
        """
        reply = self.chat(system_prompt, messages)
        if self.last_reasoning:
            yield "thinking", self.last_reasoning
        yield "text", reply

    def complete(self, system_prompt: str, user_message: str) -> str:
        return self.chat(system_prompt, [{"role": "user", "content": user_message}])


def _post_lines(url: str, payload: dict, timeout: int, what: str) -> Iterator[str]:
    """POST JSON and yield the response body line by line as it arrives."""
    req = urllib.request.Request(url, data=json.dumps(payload).encode("utf-8"),
                                 headers={"Content-Type": "application/json"}, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            for raw in resp:
                line = raw.decode("utf-8", errors="replace").strip()
                if line:
                    yield line
    except urllib.error.HTTPError as e:
        detail = e.read().decode("utf-8", errors="replace")[:500]
        raise RuntimeError(f"{what} error {e.code}: {detail}") from e
    except urllib.error.URLError as e:
        raise RuntimeError(f"Could not reach {what} at {url} (is it running?): {e}") from e
    except TimeoutError as e:
        raise RuntimeError(f"{what} timed out after {timeout}s.") from e


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

    def stream(self, system_prompt: str, messages: list[dict]) -> Iterator[tuple[str, str]]:
        payload = {
            "model": self.model,
            "messages": [{"role": "system", "content": system_prompt}, *messages],
            "stream": True,
            "options": {"temperature": 0.2, "num_ctx": self.num_ctx},
        }
        self.last_reasoning = None
        thinking: list[str] = []
        for line in _post_lines(f"{self.base_url}/api/chat", payload, self.timeout, "Ollama"):
            data = json.loads(line)
            if "error" in data:
                raise RuntimeError(f"Ollama error for model {self.model!r}: {data['error']}")
            message = data.get("message") or {}
            if message.get("thinking"):
                thinking.append(message["thinking"])
                yield "thinking", message["thinking"]
            if message.get("content"):
                yield "text", message["content"]
        self.last_reasoning = "".join(thinking) or None


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

    def stream(self, system_prompt: str, messages: list[dict]) -> Iterator[tuple[str, str]]:
        payload = {
            "messages": [{"role": "system", "content": system_prompt}, *messages],
            "temperature": 0.7, "top_p": 0.8, "top_k": 20, "min_p": 0.0,
            "max_tokens": self.max_tokens,
            "reasoning_effort": self.reasoning,
            "stream": True,
        }
        self.last_reasoning = None
        thinking: list[str] = []
        got_text = False
        url = f"{self.base_url}/v1/chat/completions"
        for line in _post_lines(url, payload, self.timeout, "llama-server"):
            if not line.startswith("data:"):
                continue
            body = line[5:].strip()
            if body == "[DONE]":
                break
            choices = json.loads(body).get("choices") or [{}]
            delta = choices[0].get("delta") or {}
            if delta.get("reasoning_content"):
                thinking.append(delta["reasoning_content"])
                yield "thinking", delta["reasoning_content"]
            if delta.get("content"):
                got_text = True
                yield "text", delta["content"]
        self.last_reasoning = "".join(thinking) or None
        if not got_text:
            raise RuntimeError("llama-server returned an empty reply (output limit hit during reasoning?).")


class AnthropicProvider(Provider):
    """
    Claude via the Anthropic API (api.anthropic.com) -- a paid API key,
    separate from a claude.ai subscription. Get one at console.anthropic.com
    and set ANTHROPIC_API_KEY.

    Defaults to Sonnet 5.5 with adaptive thinking (its default) and the
    thinking shown as a readable summary in the UI's "Thinking" block. Every
    request streams, so long replies never hit HTTP timeouts. Also on by default:
    - prompt caching (the pinned textbook pages and earlier turns are re-read
      from cache on each turn instead of billed in full);
    - server-side refusal fallbacks (`fallbacks="default"`): if a safety
      classifier declines a request, the API re-runs it on Anthropic's
      recommended fallback model. ANTHROPIC_FALLBACKS=off disables it (needed
      when ANTHROPIC_BASE_URL points somewhere other than the Claude API).
    Don't add a `temperature` override here: with thinking on, a non-default
    sampling param is a 400 on this model.
    """

    name = "anthropic"
    FALLBACK_BETA = "server-side-fallback-2026-07-01"

    def __init__(self, model: str | None = None, api_key: str | None = None):
        from anthropic import Anthropic

        self.client = Anthropic(api_key=api_key)  # reads ANTHROPIC_API_KEY if None
        self.model = model or os.environ.get("ANTHROPIC_MODEL", "claude-sonnet-5-5")
        self.max_tokens = int(os.environ.get("ANTHROPIC_MAX_TOKENS", "16000"))
        self.effort = os.environ.get("ANTHROPIC_EFFORT")  # low|medium|high|xhigh|max; unset = model default
        self.thinking_display = os.environ.get("ANTHROPIC_THINKING_DISPLAY", "summarized")  # or "omitted"
        self.fallbacks = os.environ.get("ANTHROPIC_FALLBACKS", "default").lower() not in ("off", "0", "false", "")

    def _request(self, system_prompt: str, messages: list[dict]):
        kwargs = dict(
            model=self.model,
            max_tokens=self.max_tokens,
            system=system_prompt,
            messages=messages,
            thinking={"type": "adaptive", "display": self.thinking_display},
            cache_control={"type": "ephemeral"},
        )
        if self.effort:
            kwargs["output_config"] = {"effort": self.effort}
        if self.fallbacks:
            return self.client.beta.messages.stream(betas=[self.FALLBACK_BETA], fallbacks="default", **kwargs)
        return self.client.messages.stream(**kwargs)

    def stream(self, system_prompt: str, messages: list[dict]) -> Iterator[tuple[str, str]]:
        import anthropic

        self.last_reasoning = None
        thinking: list[str] = []
        got_text = False
        try:
            with self._request(system_prompt, messages) as stream:
                for event in stream:
                    if event.type != "content_block_delta":
                        continue
                    if event.delta.type == "thinking_delta" and event.delta.thinking:
                        thinking.append(event.delta.thinking)
                        yield "thinking", event.delta.thinking
                    elif event.delta.type == "text_delta":
                        got_text = True
                        yield "text", event.delta.text
                final = stream.get_final_message()
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

        self.last_reasoning = "".join(thinking) or None
        if final.stop_reason == "refusal":
            category = final.stop_details.category if final.stop_details else None
            raise RuntimeError(f"Claude declined to answer ({category or 'no category given'}).")
        if not got_text:
            raise RuntimeError("Anthropic API returned an empty reply.")

    def chat(self, system_prompt: str, messages: list[dict]) -> str:
        return "".join(chunk for kind, chunk in self.stream(system_prompt, messages) if kind == "text")


class OpenRouterProvider(Provider):
    """
    OpenRouter (openrouter.ai): one key for hundreds of models through an
    OpenAI-compatible /api/v1/chat/completions endpoint. Set OPENROUTER_API_KEY
    (never put the key in the repo).

    OPENROUTER_MODEL is a comma-separated list tried in order. The default
    picks fast models: Claude Haiku 4.5 (starts writing in ~3s; no slow
    "thinking" phase), then a free model, so the tutor stays fast even when the
    account has no credit left -- a refused or rate-limited model falls through
    to the next in about a second instead of to a slow local model. For the
    best (but slower, ~12s to first word) tutoring use
    OPENROUTER_MODEL=anthropic/claude-sonnet-5.5.
    """

    name = "openrouter"
    DEFAULT_MODELS = "anthropic/claude-haiku-4.5,nvidia/nemotron-3-super-120b-a12b:free"

    def __init__(self, timeout: int = 120):
        self.key = os.environ.get("OPENROUTER_API_KEY", "")
        self.base_url = os.environ.get("OPENROUTER_BASE_URL", "https://openrouter.ai/api/v1").rstrip("/")
        self.models = [m.strip() for m in os.environ.get("OPENROUTER_MODEL", self.DEFAULT_MODELS).split(",") if m.strip()]
        self.model = self.models[0]
        self.max_tokens = int(os.environ.get("OPENROUTER_MAX_TOKENS", "1200"))
        self.timeout = timeout
        self.used_model: str | None = None

    @property
    def label(self) -> str:
        """Provider and the model that actually answered, for the chat's model tag."""
        return f"{self.name} · {self.used_model or self.model}"

    def _stream_model(self, model: str, system_prompt: str, messages: list[dict]) -> Iterator[tuple[str, str]]:
        payload = {"model": model, "stream": True, "max_tokens": self.max_tokens,
                   "messages": [{"role": "system", "content": system_prompt}, *messages]}
        req = urllib.request.Request(
            f"{self.base_url}/chat/completions", data=json.dumps(payload).encode("utf-8"), method="POST",
            headers={"Content-Type": "application/json", "Authorization": f"Bearer {self.key}",
                     "X-Title": "HSK ShiFu"})
        got_text = False
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                for raw in resp:
                    line = raw.decode("utf-8", errors="replace").strip()
                    if not line.startswith("data:"):
                        continue
                    body = line[5:].strip()
                    if body == "[DONE]":
                        break
                    data = json.loads(body)
                    if "error" in data:  # a mid-stream error from the upstream provider
                        raise RuntimeError(f"{model}: {data['error'].get('message', data['error'])}")
                    text = ((data.get("choices") or [{}])[0].get("delta") or {}).get("content")
                    if text:
                        got_text = True
                        yield "text", text
        except urllib.error.HTTPError as e:
            detail = e.read().decode("utf-8", errors="replace")[:300]
            if e.code == 402:
                raise RuntimeError(f"{model}: OpenRouter account has no credits for it -- add some at "
                                   "https://openrouter.ai/settings/credits") from e
            if e.code == 401:
                raise RuntimeError("OpenRouter key rejected -- check OPENROUTER_API_KEY.") from e
            raise RuntimeError(f"{model}: OpenRouter error {e.code}: {detail}") from e
        except urllib.error.URLError as e:
            raise RuntimeError(f"Could not reach OpenRouter: {e}") from e
        except TimeoutError as e:
            raise RuntimeError(f"{model}: OpenRouter timed out after {self.timeout}s.") from e
        if not got_text:
            raise RuntimeError(f"{model}: OpenRouter returned an empty reply.")

    def stream(self, system_prompt: str, messages: list[dict]) -> Iterator[tuple[str, str]]:
        if not self.key:
            raise RuntimeError("No OpenRouter key configured -- set OPENROUTER_API_KEY.")
        self.last_reasoning = None
        errors = []
        for model in self.models:
            started = False
            try:
                for kind, chunk in self._stream_model(model, system_prompt, messages):
                    if not started:
                        started, self.used_model = True, model
                    yield kind, chunk
                return
            except RuntimeError as e:
                if started or "key rejected" in str(e) or "Could not reach" in str(e):
                    raise  # mid-reply failure, or every model would fail the same way
                errors.append(str(e))
        raise RuntimeError(" | ".join(errors))

    def chat(self, system_prompt: str, messages: list[dict]) -> str:
        return "".join(c for kind, c in self.stream(system_prompt, messages) if kind == "text")


class FallbackProvider(Provider):
    """
    Tries providers in order (e.g. HSK_AGENT_PROVIDER=llamacpp,ollama: the
    local Bonsai model first, Ollama only if it fails). A provider counts as
    failed only if it errors before producing any text -- a reply that
    already started streaming is never silently swapped for another model's.
    `used` names the provider that actually answered.
    """

    def __init__(self, providers: list[Provider]):
        self.providers = providers
        self.name = ",".join(p.name for p in providers)
        self.used: str | None = None

    def stream(self, system_prompt: str, messages: list[dict]) -> Iterator[tuple[str, str]]:
        errors = []
        for p in self.providers:
            started = False
            try:
                for kind, chunk in p.stream(system_prompt, messages):
                    if not started:
                        started, self.used = True, getattr(p, "label", p.name)
                    yield kind, chunk
                self.last_reasoning = p.last_reasoning
                self.used = getattr(p, "label", p.name)
                return
            except RuntimeError as e:
                if started:
                    raise
                errors.append(f"{p.name}: {e}")
        raise RuntimeError("No tutor model is available. " + " | ".join(errors))

    def chat(self, system_prompt: str, messages: list[dict]) -> str:
        return "".join(chunk for kind, chunk in self.stream(system_prompt, messages) if kind == "text")


PROVIDERS: dict[str, type[Provider]] = {
    "ollama": OllamaProvider,
    "llamacpp": LlamaCppProvider,
    "anthropic": AnthropicProvider,
    "openrouter": OpenRouterProvider,
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
    if "," in name:  # a priority list, e.g. "llamacpp,ollama"
        return FallbackProvider([get_provider(n.strip()) for n in name.split(",") if n.strip()])
    provider_cls = PROVIDERS.get(name)
    if provider_cls is None:
        available = ", ".join(PROVIDERS) or "(none registered yet)"
        raise ValueError(f"Unknown provider {name!r}. Available: {available}")
    return provider_cls()
