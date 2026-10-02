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

## Teach mode (virtual teacher)

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

### Adding another provider (Anthropic, OpenAI, Gemini, ...)

None of the cloud providers are wired up yet (by design, until one is chosen). To add one:

1. Open `agent/providers.py`.
2. Subclass `Provider`, implement `complete(system_prompt, user_message) -> str`.
3. Add it to the `PROVIDERS` dict.
4. Set `HSK_AGENT_PROVIDER=<name>` (env var) or pass `--provider <name>` / `"provider": "<name>"` to the CLI/API.

A worked example (Anthropic) is commented directly in `providers.py`, following the same shape as `OllamaProvider`.
