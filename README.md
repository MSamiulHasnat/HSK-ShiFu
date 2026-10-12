# HSK ShiFu

**A Chinese tutor that only teaches what's in the textbook.**

HSK ShiFu is a complete study app for HSK 1–3 candidates: an AI tutor named 王老师 (Wáng lǎoshī), spaced-repetition flashcards, exam-style drills, timed practice tests, a course browser and a dictionary. Every word, sentence and grammar point in it comes from the official *HSK Standard Course* textbooks (Levels 1–3), with a page citation that opens the scanned book page.

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
| Proof | "Trust me" | Every citation opens the scanned textbook page |

The language model only *writes* the tutor's replies. What it's allowed to say is decided by retrieval from the textbooks, and everything outside the chat (flashcards, drills, tests, dictionary) involves no language model at all.

---

## Features

### Study app (works with no language model)

- **Today dashboard.** Cards due, new words for today, streak, accuracy, vocabulary coverage per HSK level, where to continue in the course, the words you keep missing, and recent test scores. Pick the HSK level you're preparing for.
- **Spaced-repetition flashcards.** All 596 syllabus words, introduced in textbook order with a daily limit, scheduled Anki-style (Again / Hard / Good / Easy, learning steps, growing intervals). Each card shows the book's pinyin, meaning, page and an example sentence from the lesson. Keyboard-driven, with audio.
- **Exam-style drills.** Six question types built from the books: meaning, characters, pinyin and tones, listening, fill-the-gap (选词填空) and sentence ordering (连词成句). Wrong options are real book words, filtered so none can also be correct. Every answer shows its source page.
- **Timed practice tests.** 30 questions in sections (listening, reading, fill-the-blank, plus sentence building at HSK 3), 25 minutes, no feedback until the end, then a section breakdown and a review of every mistake. Clearly labelled as practice material, not an official paper.
- **Course browser.** All 50 lessons with titles, page ranges, word lists (with your progress on each word), the 136 grammar points and the lesson's sentences, with pinyin and English where the book prints them.
- **Dictionary.** Search the 717 textbook words by characters, pinyin (tones optional) or English. Each entry shows its lesson, page, the book's sentences that use it, and other entries for the same characters.
- **Scanned-page viewer.** Every 📖 citation, anywhere in the app, opens the actual book page alongside its transcript.
- **Tap any word.** Chinese words in the tutor's replies, sentences and examples are linked to their textbook entry, with audio and "add to flashcards".

### 王老师, the tutor

- **Streaming replies** with the model's thinking shown live (collapsible) when the model provides it.
- **Focused lessons.** Start from any lesson, grammar point, word, or your weak words; the tutor pins exactly those textbook pages plus the book's word-list entries, and knows which HSK level you're preparing for.
- **Teaching style.** Small steps, one question at a time, diagnoses *why* an answer is wrong (vocabulary, grammar pattern, or tone), never leaks the answer, role-plays the lesson dialogues.
- **Automatic checks on every reply.** Citations must be pages the tutor was given; examples shown under a citation must be on that page; every 汉字 (pinyin) example is looked up across the books and marked either "✓ from the textbook, page N" or "the tutor's own example"; and if the tutor calls a correct answer wrong while giving the student's own sentence as the "correction", the reply is flagged.
- **Persistent conversations** with a history drawer.
- **Swappable model backends.** Run fully local (Ollama, or a llama.cpp server) or use Claude through the Anthropic API.

### Also

- **Teach mode and grounded Q&A** from the command line (`agent/cli.py`).
- **HTTP API** for everything above, documented at `/docs`.

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
│  course.py ───── the books as data: 717 words, 50 lessons,      │
│  lexicon.py      136 grammar points, 1,600+ sentences, each     │
│                  with its page (no LLM)                         │
│       │                                                         │
│       ├─► srs.py · progress.py ── flashcard scheduling and the  │
│       │                           learning record (SQLite)      │
│       ├─► quiz.py ─────────────── drills and practice tests     │
│       ▼                                                         │
│  retrieval.py ── finds relevant graph nodes + textbook pages    │
│       │                                                         │
│       ▼                                                         │
│  prompts.py ──── one shared rule set (grounding, citations,     │
│       │          diagnosis, language) used by every mode        │
│       ▼                                                         │
│  providers.py ── Ollama · llama.cpp · Anthropic (Claude),       │
│       │          all streaming                                  │
│       ▼                                                         │
│  tutor.py / teacher.py ── chat and lessons, plus fact checks    │
│  verify.py ────────────── every example looked up in the books  │
│       │                                                         │
│       ▼                                                         │
│  server.py · api_study.py · static/ ── HTTP API and web app     │
│  cli.py ───────────────────────────── command line              │
└─────────────────────────────────────────────────────────────────┘
```

The course layer parses the transcripts deterministically: the back-of-book vocabulary index (词语总表), each lesson's numbered "New Words" lists, the tables of contents, the "注释 Notes" grammar sections, and the dialogues. It is conservative where accuracy matters: a sentence keeps its pinyin only if the book's own pinyin for the words in it matches, and its English only if the dialogue and its "English Version" line up one-to-one, so nothing is ever shown with someone else's translation.

Neither the course layer nor retrieval calls a language model. The model only writes the tutor's prose from material retrieval already selected, and code checks the result afterwards.

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

### 2. Pick a model (for the tutor only)

Flashcards, drills, tests, the course and the dictionary work without a model. The tutor chat needs one. The fastest way to start is Ollama:

```bash
ollama pull gemma3n:e4b
export HSK_AGENT_PROVIDER=ollama
```

See [Choosing a model](#choosing-a-model-providers) for the other options.

### 3. Start the app

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

Defaults: model `claude-sonnet-5-5`, `max_tokens` 16000, streaming, prompt caching (the pinned textbook pages are re-read from cache on later turns), thinking shown as a readable summary, and server-side refusal fallbacks (`fallbacks="default"`: if a safety classifier declines a request, the API re-runs it on Anthropic's recommended fallback model). Set `ANTHROPIC_EFFORT` to `low` through `max` to trade cost against quality, or `ANTHROPIC_MODEL=claude-opus-5-5` for the most capable tutor.

For a fuller description of each provider, including the model-specific notes, see [`agent/README.md`](agent/README.md).

---

## Using it

### A study day

1. **Today**: pick the HSK level you're preparing for, then press **Start review**.
2. **Review**: <kbd>Space</kbd> shows the answer, <kbd>1</kbd>–<kbd>4</kbd> grades it, <kbd>R</kbd> replays the audio. New words arrive in textbook order, up to your daily limit (Today → Settings).
3. **Course**: open the next lesson; **Learn these words** queues all its words, **Study with 王老师** starts a tutor session on it, **Drill this lesson** quizzes it.
4. **Practice**: a quick drill (pick level, lesson and question types) or a timed **practice test**. Mistakes can be drilled again or gone over with 王老师.
5. **Dictionary**: look anything up by characters, pinyin or English.

Tap any underlined Chinese word for its textbook entry, and any 📖 citation to see the scanned page.

Audio uses your device's own Chinese text-to-speech voice. If none is installed, add one in your operating system's language settings. The pinyin shown in the app is always the textbook's.

### The tutor chat

Open **Tutor** and pick a starter (study a lesson, role-play its dialogue, explain a grammar point, review your weak words), or say what you want to learn, for example *"Teach me 把字句"* or *"HSK 2 lesson 5"*.

- The tutor teaches one small idea, cites the textbook page, and asks **one** question.
- Answer in Chinese or English. Explanations stay in the language you started with.
- If an answer is wrong, the tutor says what kind of mistake it is before correcting it.
- Under each reply, **Sentence check** lists the Chinese examples it used: ✓ with the page for textbook sentences, or "the tutor's own example". A ⚠️ **Fact check** box appears if a citation or example doesn't verify.
- **+ New** starts fresh; **History** lists past conversations.
- A 🤔 **Thinking** block shows the model's reasoning when the model provides one.

### Inside your AI assistant (no model or API key needed)

If you already use Claude Code, Codex, GitHub Copilot in VS Code, Kimi or a similar assistant, it can be the tutor. Open the repo and ask, e.g. *"Teach me 把字句"*.

The repo is set up so the assistant doesn't read the over-a-million tokens of textbook data:

- **Instructions:** `CLAUDE.md`, `AGENTS.md`, `GEMINI.md` and `.github/copilot-instructions.md` tell it to use the lookups below and not open the data folders.
- **MCP tools:** `python -m agent.mcp_server` (`hsk_context`, `hsk_word`, `hsk_grammar`, `hsk_lesson`, ...) is registered in `.mcp.json` (Claude Code) and `.vscode/mcp.json` (Copilot). For other assistants, add it as a stdio MCP server, e.g. `codex mcp add hsk-shifu -- python -m agent.mcp_server`.
- **Command line,** for assistants without MCP: `python -m agent.ask context "What does 已经 mean?"` returns the book's entry, sentences and page citations in a few hundred tokens.
- **Hard blocks where supported:** Claude Code is denied reads of the data folders (`.claude/settings.json`), VS Code search skips them (`.vscode/settings.json`), and Cursor ignores them (`.cursorignore`). Other assistants rely on the instructions.

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

**Tutor and Q&A**

| Method | Endpoint | Purpose |
|---|---|---|
| `GET` | `/` | The study app |
| `POST` | `/chat` | Send a tutor message. Body: `{"message", "session_id", "provider", "focus"}` |
| `POST` | `/chat/stream` | Same body; Server-Sent Events `meta`, `thinking`, `delta`, `done` (or `error`) |
| `POST` | `/chat/reset` | Delete a conversation. Body: `{"session_id"}` |
| `GET` | `/chat/sessions` | List saved conversations |
| `GET` | `/chat/sessions/{id}` | Full history for one conversation, with sentence checks |
| `POST` | `/ask` | One-shot answer or lesson. Body: `{"question", "mode": "answer" \| "teach", "dfs", "budget", "provider"}` |
| `GET` | `/api/status` | Which provider and model the tutor uses |
| `GET` | `/graph/info` | Node, edge, and hyperedge counts |
| `GET` | `/healthz` | Liveness check |

`focus` (optional) pins the tutor to a study target: `{"type": "lesson", "level": 2, "lesson": 5}`, `{"type": "grammar", "level": 3, "lesson": 11, "page": 109}`, `{"type": "word", "id": "2:已经"}`, or `{"type": "review", "word_ids": [...]}` (omit the ids to use your weakest words).

**Study features** (no language model involved)

| Method | Endpoint | Purpose |
|---|---|---|
| `GET` | `/api/course` | All lessons per level, with your mastery of each |
| `GET` | `/api/course/{level}/{lesson}` | One lesson: words, grammar points, sentences |
| `GET` | `/api/words/search?q=` | Search by characters, pinyin or English |
| `GET` | `/api/words/{id}` | One entry, its textbook sentences and other entries for the same characters |
| `GET` | `/api/lexicon` | Compact word list used to make words clickable in the browser |
| `GET` | `/api/page/{level}/{page}` | A textbook page: transcript, lesson, printed page; `.../image` for the scan |
| `GET` | `/api/review/queue?limit=&level=&lesson=` | Flashcards due now, then new words |
| `POST` | `/api/review/answer` | Grade a card. Body: `{"word_id", "grade": 1-4}` |
| `POST` | `/api/review/add` | Put a word into your flashcards. Body: `{"word_id"}` |
| `GET` | `/api/drill?level=&lesson=&types=&count=&word_ids=` | Practice questions |
| `POST` | `/api/drill/answer` | Record a drill answer. Body: `{"word_id", "correct", "mode"}` |
| `GET` | `/api/test/{level}` | A 30-question practice test |
| `POST` | `/api/test/result` | Save a test score |
| `GET` | `/api/progress` | Streak, accuracy, coverage per level, activity, weak words, test history |
| `GET` / `POST` | `/api/settings` | `target_level` (1-3) and `daily_new` |
| `POST` | `/api/progress/reset` | Erase the learning record. Body: `{"confirm": "RESET"}` |

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
| `ANTHROPIC_MAX_TOKENS` | `16000` | Reply length cap (thinking counts toward it) |
| `ANTHROPIC_EFFORT` | *(model default)* | `low` · `medium` · `high` · `xhigh` · `max` |
| `ANTHROPIC_THINKING_DISPLAY` | `summarized` | `summarized` shows a readable thinking summary in the chat; `omitted` hides it |
| `ANTHROPIC_FALLBACKS` | `default` | Server-side refusal fallbacks; `off` disables them (needed if `ANTHROPIC_BASE_URL` points somewhere other than the Claude API) |

---

## Project layout

```
HSK-ShiFu/
├── agent/                  Standalone agent: retrieval, prompts, providers, server, CLI
│   ├── server.py           FastAPI app (tutor API + web app)
│   ├── api_study.py        Study-feature API (/api/...)
│   ├── course.py           The books as data: words, lessons, grammar points
│   ├── course_sentences.py Example sentences, with pinyin/English only when certain
│   ├── course_text.py      Page access and hanzi/pinyin helpers
│   ├── lexicon.py          Lookup, search, segmentation, lesson references
│   ├── srs.py              Spaced-repetition scheduling
│   ├── progress.py         The learning record (SQLite)
│   ├── quiz.py             Drills and practice tests
│   ├── tutor.py            Multi-turn tutor chat, topics, streaming
│   ├── verify.py           Looks up every tutor example in the books
│   ├── teacher.py          One-shot teach mode and citation fact checks
│   ├── retrieval.py        Graph and textbook-page retrieval
│   ├── prompts.py          Shared instruction set used by every mode
│   ├── providers.py        Ollama, llama.cpp, and Anthropic backends (streaming)
│   ├── chat_store.py       SQLite storage for chat sessions
│   ├── static/             The web app (no build step): index.html, css/, js/
│   └── README.md           Detailed agent documentation
├── tests/                  Unit and API tests (python -m unittest discover -s tests -t .)
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

`agent/data/` holds local chat history and your learning record (`progress.db`), and is git-ignored.

### Tests

```bash
python -m unittest discover -s tests -t .
```

The suite checks the parser against facts printed in the books (word counts, pages, titles, that every extracted sentence is verbatim from its page), the scheduler, that every generated question's answer is the book's own fact and no distractor can also be right, the learning record, the tutor pipeline with a scripted model, and the whole HTTP API, including streaming, on a live local server. It needs no extra packages and never touches `agent/data/`.

---

## Data and copyright

The grounding corpus is derived from the official *HSK Standard Course* textbooks, published by Beijing Language and Culture University Press. The transcriptions in `hsk_data/` and the knowledge graph in `graphify-out/` contain the textbook content itself.

- Use this project for personal study and research.
- Check the publisher's terms before redistributing the transcriptions, the graph, or the source PDFs.
- The source PDFs in `HSK-Textbooks/` are included in the repository's history. If you plan to make the repository public or share it widely, consider removing them and linking to the publisher's official copies instead.

---

## Known limitations

- **Small local models make mistakes.** A 4-billion-parameter model follows the lesson structure but sometimes misdiagnoses errors (in testing, gemma3n called a correct 把 sentence wrong) or presents its own sentences as the book's. The checks flag both cases, but they can't make the model reason better. Larger models, especially Claude, give noticeably better tutoring.
- **Local models are slow to start a topic.** A new topic means the model reads about 3,500 tokens of textbook pages first; on CPU that can take a few minutes. Later turns reuse the cached prompt and start in seconds. If llama-server is holding the GPU, Ollama falls back to the CPU.
- **Large local models can be slow.** The Bonsai 2 27B ternary model runs at roughly 1.4 tokens per second on a 6 GB GPU, so a single reply takes one to three minutes. Reasoning mode makes this far worse.
- **Practice tests are practice.** They're built from the textbooks' words and sentences in exam-like sections, not taken from official HSK papers, and the app doesn't claim any score maps to an exam result.
- **Some sentences have no pinyin or English.** They're attached only where the book prints them and they can be matched with certainty (Level 3 dialogues carry no English in the book).
- **No image input yet.** The tutor works from text only. Vision support is planned, and Claude models would support it natively.
- **Teach-mode lessons can be truncated** when `LLAMACPP_MAX_TOKENS` is set low.
- **Chat history stays on this machine.** Sessions are stored in a local SQLite file and are never sent anywhere except to the model you configure.

---

## Further reading

- [`agent/README.md`](agent/README.md): the full agent guide, including provider details and the chat tutor's behavior
- [`INGESTION_REPORT.md`](INGESTION_REPORT.md): how the textbook corpus was transcribed and what was skipped
- [`CLAUDE.md`](CLAUDE.md) and [`AGENTS.md`](AGENTS.md): grounding rules for coding-agent integrations
