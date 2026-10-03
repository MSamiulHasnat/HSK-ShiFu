# HSK Agent — standalone CLI / API path

This is the integration path for using the HSK knowledge graph **outside** a coding agent (Claude Code / Antigravity / Codex) — e.g. your own script, a web UI, or just the terminal with your own LLM API key.

Every answer is still pulled strictly from `graphify-out/graph.json` (see `../AGENTS.md` for the grounding rules — the same rules apply here). This package never invents Chinese-language facts; the only thing it adds on top of retrieval is optional LLM synthesis for readability.

## How it fits together

```
your question
     │
     ▼
agent/retrieval.py   ──► shells out to `graphify query` (same tool the coding agents use)
     │                    returns cited graph nodes, or "not found"
     ▼
agent/prompts.py     ──► wraps the retrieved context + strict grounding rules
     │
     ▼
agent/providers.py   ──► OPTIONAL: hands it to a configured LLM to write a readable answer
                          (no provider configured yet — see below)
```

If no LLM provider is configured, you still get a fully grounded answer — just as the raw retrieved graph facts (node labels + citations) instead of LLM-written prose. This is intentional: retrieval never depends on having an API key.

## CLI

```bash
pip install -r ../requirements.txt
python -m agent.cli "What does 把字句 mean?"
python -m agent.cli --dfs "How does the 把-construction connect to the passive voice?"
```

## Web server

```bash
python -m agent.server
# -> http://127.0.0.1:8000
```

- `POST /ask` — `{"question": "...", "dfs": false, "budget": 2000}` → grounded answer + citations
- `GET /graph/info` — node/edge/community counts
- `GET /healthz` — liveness check

## Chat tutor (interactive, multi-turn)

The web UI at `http://localhost:8000` is a chat with 王老师: tell it what you want to learn, it teaches one small step, asks you a question, waits for your answer, says whether it's right and why, and follows up. API: `POST /chat {"message": "...", "session_id": null}` → pass the returned `session_id` back to continue; `POST /chat/reset {"session_id": "..."}` to delete a conversation; `GET /chat/sessions` to list past conversations; `GET /chat/sessions/{id}` to fetch one's full history (`agent/tutor.py`).

- **Grounding is per topic.** When you ask to learn something ("teach me 了"), the explaining pages are located and pinned to the session; your practice answers don't trigger new searches.
- **Explanation language** is fixed from your first message (English stays English even while you practise in Chinese).
- **Fact check** on every tutor message: citations must be pinned pages, and a cited `汉字 (pinyin)` example must appear on that page.
- **Chat history persists** across server restarts in a local SQLite file (`agent/data/chat_sessions.db`, git-ignored). The sidebar in the web UI lists past conversations by title (the first message) and lets you resume or delete them. The 6-hour idle TTL only evicts a conversation from the in-memory cache, not from storage.
- Known limit with small local models: they follow the conversation well but can misdiagnose *why* an answer is wrong. A larger model (e.g. a 7B+ Qwen, which is strong at Chinese) helps most here.

## Teach mode (one-shot lesson)

`python -m agent.cli --teach "Teach me 把字句"`, or pick "Teach me" in the web UI (`"mode": "teach"` in the `/ask` body).

How it stays grounded (`agent/teacher.py`):

1. The Chinese term is pulled out of the question and the transcripts are searched directly for the section that **explains** it (grammar headings with the term quoted, e.g. `### 3 "了"表变化`) -- the graph alone sometimes points at table-of-contents pages instead.
2. Those full textbook pages are given to the model with a teacher prompt: what it is → the book's explanation and examples (cited) → how to use it → an optional **Teacher's note (not from the textbook)** → practice questions.
3. After the model answers, code checks it: every citation must be a page the model was actually given, and every Chinese example sentence shown under a citation must actually appear on that page. Anything invented or mis-cited is flagged in a ⚠️ Fact check block at the end of the lesson.

Small local models (e.g. `gemma3n:e4b`) follow the lesson structure but do sometimes mis-cite or improvise; the fact check catches that, but a larger model gives noticeably better lessons.

## LLM providers

### Ollama (local, no API key)

Wired up and ready. Requires [Ollama](https://ollama.com) running locally:

```bash
ollama pull gemma3n:e4b      # or any model you prefer
export HSK_AGENT_PROVIDER=ollama
python -m agent.cli "What does 把字句 mean?"
```

Defaults: model `gemma3n:e4b` (override with `OLLAMA_MODEL`), server `http://localhost:11434` (override with `OLLAMA_BASE_URL`). Or per-call: `python -m agent.cli --provider ollama "..."` / `{"provider": "ollama"}` in the `/ask` request body.

### llama.cpp / llama-server (local, no API key)

For GGUF models `ollama` can't run (e.g. ternary quants like Bonsai 2 27B) -- points at any OpenAI-compatible `llama-server`:

```bash
export HSK_AGENT_PROVIDER=llamacpp
export LLAMACPP_BASE_URL=http://localhost:8080   # default
```

Defaults: `reasoning_effort=none` (override with `LLAMACPP_REASONING`), `max_tokens` 2048 (16384 if reasoning is on; override with `LLAMACPP_MAX_TOKENS`).

### Anthropic (Claude, paid API key)

Note: this is the Anthropic **API**, billed per-token at console.anthropic.com -- separate from a claude.ai subscription, which doesn't include API access.

```bash
pip install anthropic   # already in requirements.txt
export ANTHROPIC_API_KEY=sk-ant-...
export HSK_AGENT_PROVIDER=anthropic
python -m agent.cli "What does 把字句 mean?"
```

Defaults: model `claude-sonnet-5-5` (override with `ANTHROPIC_MODEL`), `max_tokens` 4096 (override with `ANTHROPIC_MAX_TOKENS`). Thinking is left on at the model's own default effort; set `ANTHROPIC_EFFORT` (`low`/`medium`/`high`/`xhigh`/`max`) to tune cost vs. quality.

### Adding another provider (OpenAI, Gemini, ...)

1. Open `agent/providers.py`.
2. Subclass `Provider`, implement `chat(system_prompt, messages) -> str` (the base class derives `complete(system_prompt, user_message)` from it for free).
3. Add it to the `PROVIDERS` dict.
4. Set `HSK_AGENT_PROVIDER=<name>` (env var) or pass `--provider <name>` / `"provider": "<name>"` to the CLI/API.
