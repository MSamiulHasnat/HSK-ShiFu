# HSK ShiFu

**A Chinese tutor that only teaches what's in the textbook.**

HSK ShiFu answers questions about HSK Chinese vocabulary, grammar, and exam content, and it runs interactive practice sessions with a tutor named 王老师 (Wáng lǎoshī). Every fact it states is retrieved from a knowledge graph built from the official *HSK Standard Course* textbooks (Levels 1–3), and every claim comes with a page citation.

It never answers from general knowledge of Chinese. If the textbooks don't cover something, it says so.

---

## Contents

- [Why it's different](#why-its-different)
- [Features](#features)
- [How it works](#how-it-works)
- [Quick start](#quick-start)
- [Choosing a model (providers)](#choosing-a-model-providers)
- [Using it](#using-it)
- [HTTP API](#http-api)
- [Configuration reference](#configuration-reference)
- [Project layout](#project-layout)
- [Data and copyright](#data-and-copyright)
- [Known limitations](#known-limitations)
- [Further reading](#further-reading)

---

## Why it's different

Most "AI tutors" answer from whatever the model happens to remember, which means confident-sounding mistakes about grammar and characters. HSK ShiFu inverts that:

| | Typical AI tutor | HSK ShiFu |
|---|---|---|
| Source of facts | The model's training data | The HSK textbooks, via a knowledge graph |
| Citations | Often missing or invented | Every textbook fact cites `(HSK Level N, page N)` |
| Unknown topics | Guesses | Says *"This isn't covered in the HSK textbook materials I have access to."* |
| Fact checking | None | Code checks every citation and example sentence against the page text |

The language model only *writes* the answer. What it's allowed to say is decided by retrieval from the textbooks.

---

## Features

- **Grounded Q&A.** Ask a question, get a short answer with citations, or the honest "not covered" message.
- **Teach mode.** A structured one-shot lesson: what it is, the textbook's own examples, how to use it, optional clearly-labelled teacher's notes, and practice questions.
- **Interactive tutor chat.** A multi-turn conversation that teaches in small steps, asks one question at a time, diagnoses *why* a practice answer is wrong (vocabulary gap, grammar pattern, or tone), and never leaks the answer.
- **Persistent chat sessions.** Conversations are saved locally. A sidebar lists past sessions so you can resume or delete them.
- **Automatic fact checking.** Citations must point at pages the model was actually given, and Chinese example sentences shown under a citation must really appear on that page. Anything that doesn't is flagged.
- **Swappable model backends.** Run fully local (Ollama, or a llama.cpp server) or use Claude through the Anthropic API.
- **Reasoning trace (optional).** Models that support it can show their thinking in a collapsible block in the chat UI.
- **Browser UI and HTTP API.** A single-page chat app and a FastAPI server, plus a command-line interface.

---

## How it works

```
   HSK textbook PDFs (scanned, no text layer)
                │
                ▼  ingest/extract_pages.py  (lossless image extraction)
   hsk_data/page_images/level{1,2,3}/page_NNN.png
                │
                ▼  vision transcription, page by page
   hsk_data/transcripts/level{1,2,3}/page_NNN.md      ← grounding corpus
                │
                ▼  graphify  (knowledge graph build)
   graphify-out/graph.json                            ← 1,708 nodes · 2,315 edges
                │
┌───────────────┴─────────────────────────────────────────────────┐
│ agent/                                                          │
│                                                                 │
│  retrieval.py ── finds relevant graph nodes + textbook pages    │
│       │                                                         │
│       ▼                                                         │
│  prompts.py ──── one shared rule set (grounding, citations,     │
│       │          diagnosis, language) used by every mode        │
│       ▼                                                         │
│  providers.py ── Ollama · llama.cpp · Anthropic (Claude)        │
│       │                                                         │
│       ▼                                                         │
│  teacher.py / tutor.py ── lessons and chat, plus fact checks    │
│       │                                                         │
│       ▼                                                         │
│  server.py · cli.py ──── HTTP API, web UI, command line         │
└─────────────────────────────────────────────────────────────────┘
```

The retrieval layer never calls a language model. The model only writes prose from material retrieval already selected, and code checks the result afterwards.

---

## Quick start

### 1. Install

```bash
git clone https://github.com/MSamiulHasnat/HSK-ShiFu.git
cd HSK-ShiFu
pip install -r requirements.txt
```

`requirements.txt` includes the knowledge-graph tool (`graphifyy`), the web server (FastAPI, Uvicorn), and the Anthropic SDK.

The knowledge graph is already built and committed in `graphify-out/`, so you don't need to rebuild it.

### 2. Pick a model

Choose one of the backends below. The fastest way to start is Ollama:

```bash
ollama pull gemma3n:e4b
export HSK_AGENT_PROVIDER=ollama
```

See [Choosing a model](#choosing-a-model-providers) for the other options.

### 3. Start the web UI

```bash
python -m agent.server
```

Open **http://127.0.0.1:8000** in your browser.

### 4. Or ask from the terminal

```bash
python -m agent.cli "What does 把字句 mean?"
python -m agent.cli --teach "Teach me 把字句"
```

---

## Choosing a model (providers)

Set `HSK_AGENT_PROVIDER` to one of the names below. Without a provider, `/ask` still returns the raw retrieved textbook context, but the tutor chat and teach mode need one and will return an error.

| Provider | `HSK_AGENT_PROVIDER` | Runs where | Cost | Best for |
|---|---|---|---|---|
| **Ollama** | `ollama` | Local (CPU/GPU) | Free | Easy local setup, fast replies |
| **llama.cpp** | `llamacpp` | Local, any OpenAI-compatible `llama-server` | Free | Quantized models Ollama can't run |
| **Anthropic** | `anthropic` | Anthropic API | Pay-per-token | Best tutoring quality |

> **Note:** a claude.ai Pro or Max subscription does **not** include API access. The Anthropic provider needs an API key from [console.anthropic.com](https://console.anthropic.com), billed separately.

### Ollama

```bash
ollama pull gemma3n:e4b
export HSK_AGENT_PROVIDER=ollama
```

Defaults: model `gemma3n:e4b`, server `http://localhost:11434`, context 16384 tokens.

### llama.cpp (local `llama-server`)

Point it at any OpenAI-compatible `llama-server`, such as a build of the PrismML fork for the ternary Bonsai 2 27B model:

```bash
export HSK_AGENT_PROVIDER=llamacpp
export LLAMACPP_BASE_URL=http://localhost:8080
```

Reasoning is off by default. Set `LLAMACPP_REASONING=medium` to enable it. Expect much slower replies on large ternary models.

### Anthropic (Claude)

```bash
export ANTHROPIC_API_KEY=sk-ant-...
export HSK_AGENT_PROVIDER=anthropic
```

Defaults: model `claude-sonnet-5-5`, `max_tokens` 4096. Set `ANTHROPIC_EFFORT` to `low` through `max` to trade cost against quality.

For a fuller description of each provider, including the model-specific notes, see [`agent/README.md`](agent/README.md).

---

## Using it

### The tutor chat

Open the web UI and say what you want to learn, for example *"Teach me 把字句"*, or tap one of the suggestion chips.

- The tutor teaches one small idea, cites the textbook page, and asks **one** question.
- Answer in Chinese or English. Explanations stay in the language you started with.
- If an answer is wrong, the tutor says what kind of mistake it is before correcting it.
- Use **+ New lesson** to start fresh. Past conversations stay in the sidebar, and **×** deletes one.
- If the reply includes a 🤔 **Thinking** block, that's the model's reasoning trace. It only appears when reasoning is enabled.

### Teach mode

```bash
python -m agent.cli --teach "Teach me 了"
```

Produces a five-part lesson, followed by a fact-check report if anything didn't verify.

### Graph queries

The graphify tool is available directly for graph-level questions:

```bash
graphify query "把 construction"
graphify path "把字句" "passive voice"
graphify explain "了"
```

---

## HTTP API

Interactive docs are served at **`/docs`** when the server is running.

| Method | Endpoint | Purpose |
|---|---|---|
| `GET` | `/` | Browser chat UI |
| `POST` | `/chat` | Send a tutor message. Body: `{"message", "session_id", "provider"}` |
| `POST` | `/chat/reset` | Delete a conversation. Body: `{"session_id"}` |
| `GET` | `/chat/sessions` | List saved conversations |
| `GET` | `/chat/sessions/{id}` | Full history for one conversation |
| `POST` | `/ask` | One-shot answer or lesson. Body: `{"question", "mode": "answer" \| "teach", "dfs", "budget", "provider"}` |
| `GET` | `/graph/info` | Node, edge, and hyperedge counts |
| `GET` | `/healthz` | Liveness check |

Example:

```bash
curl -s -X POST http://127.0.0.1:8000/ask \
  -H "Content-Type: application/json" \
  -d '{"question": "What does 了 mean?"}'
```

---

## Configuration reference

### General

| Variable | Default | Purpose |
|---|---|---|
| `HSK_AGENT_PROVIDER` | *(none)* | Which provider to use: `ollama`, `llamacpp`, or `anthropic` |

### Ollama

| Variable | Default | Purpose |
|---|---|---|
| `OLLAMA_MODEL` | `gemma3n:e4b` | Model name |
| `OLLAMA_BASE_URL` | `http://localhost:11434` | Server address |
| `OLLAMA_NUM_CTX` | `16384` | Context window in tokens |

### llama.cpp

| Variable | Default | Purpose |
|---|---|---|
| `LLAMACPP_BASE_URL` | `http://localhost:8080` | Server address |
| `LLAMACPP_REASONING` | `none` | Reasoning effort (`none`, `low`, `medium`, `high`, ...) |
| `LLAMACPP_MAX_TOKENS` | `2048` (or `16384` with reasoning) | Reply length cap |

### Anthropic

| Variable | Default | Purpose |
|---|---|---|
| `ANTHROPIC_API_KEY` | *(required)* | API key from console.anthropic.com |
| `ANTHROPIC_MODEL` | `claude-sonnet-5-5` | Model ID |
| `ANTHROPIC_MAX_TOKENS` | `4096` | Reply length cap |
| `ANTHROPIC_EFFORT` | *(model default)* | `low` · `medium` · `high` · `xhigh` · `max` |

---

## Project layout

```
HSK-ShiFu/
├── agent/                  Standalone agent: retrieval, prompts, providers, server, CLI
│   ├── server.py           FastAPI app (API + web UI)
│   ├── cli.py              Command-line interface
│   ├── tutor.py            Multi-turn tutor chat and session handling
│   ├── teacher.py          One-shot teach mode and fact checks
│   ├── retrieval.py        Graph and textbook-page retrieval
│   ├── prompts.py          Shared instruction set used by every mode
│   ├── providers.py        Ollama, llama.cpp, and Anthropic backends
│   ├── chat_store.py       SQLite storage for chat sessions
│   ├── static/index.html   Browser chat UI
│   └── README.md           Detailed agent documentation
├── ingest/
│   └── extract_pages.py    PDF → page-image extraction
├── graphify-out/           Built knowledge graph (graph.json, GRAPH_REPORT.md, ...)
├── hsk_data/
│   ├── transcripts/        Page-by-page textbook transcriptions (grounding corpus)
│   └── page_images/        Extracted page images
├── HSK-Textbooks/          Source PDFs (see Data and copyright)
├── CLAUDE.md, AGENTS.md, GEMINI.md
│                           Standing instructions for coding-agent integrations
├── INGESTION_REPORT.md     How the transcription corpus was built
└── requirements.txt
```

`agent/data/` holds local chat history and is git-ignored.

---

## Data and copyright

The grounding corpus is derived from the official *HSK Standard Course* textbooks, published by Beijing Language and Culture University Press. The transcriptions in `hsk_data/` and the knowledge graph in `graphify-out/` contain the textbook content itself.

- Use this project for personal study and research.
- Check the publisher's terms before redistributing the transcriptions, the graph, or the source PDFs.
- The source PDFs in `HSK-Textbooks/` are included in the repository's history. If you plan to make the repository public or share it widely, consider removing them and linking to the publisher's official copies instead.

---

## Known limitations

- **Small local models make mistakes.** A 4-billion-parameter model follows the lesson structure but sometimes misdiagnoses errors or improvises citations. The fact checker catches many of these, but not all. Larger models give noticeably better results.
- **Large local models can be slow.** The Bonsai 2 27B ternary model runs at roughly 1.4 tokens per second on a 6 GB GPU, so a single reply takes one to three minutes. Reasoning mode makes this far worse.
- **No image input yet.** The tutor works from text only. Vision support is planned, and Claude models would support it natively.
- **Teach-mode lessons can be truncated** when `LLAMACPP_MAX_TOKENS` is set low.
- **Chat history stays on this machine.** Sessions are stored in a local SQLite file and are never sent anywhere except to the model you configure.

---

## Further reading

- [`agent/README.md`](agent/README.md): the full agent guide, including provider details and the chat tutor's behavior
- [`INGESTION_REPORT.md`](INGESTION_REPORT.md): how the textbook corpus was transcribed and what was skipped
- [`CLAUDE.md`](CLAUDE.md) and [`AGENTS.md`](AGENTS.md): grounding rules for coding-agent integrations
