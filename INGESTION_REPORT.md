# HSK Textbook Ingestion Report

**Date:** 2026-10-02
**Status:** Transcription complete (500/500 pages accounted for). Knowledge graph and agent layer not yet built.

## Source material

| Level | File | PDF pages |
|---|---|---|
| 1 | `HSK-Textbooks/HSK-Level1-Version2.0.pdf` | 142 |
| 2 | `HSK-Textbooks/HSK-Level2-Version2.0.pdf` | 151 |
| 3 | `HSK-Textbooks/HSK-Level3-Version2.0.pdf` | 207 |
| **Total** | | **500** |

These are "HSK Standard Course" (HSK 标准教程), the official bilingual Chinese/English textbook series (Beijing Language and Culture University Press / Hanban-affiliated). **All three PDFs are scanned image pages with no embedded text layer** — every page is a single full-page image, not extractable text. This was confirmed by sampling pages across all three books (0 extractable characters per page via `pypdf`/`pdfplumber`).

## Pipeline

1. **Page extraction** (`ingest/extract_pages.py`): losslessly extracts each page's embedded image (one XObject per page) to `hsk_data/page_images/level{1,2,3}/page_NNN.png`, zero-padded 3-digit, 1:1 with PDF page number. Deterministic, no LLM involved. 500/500 extracted successfully.
2. **Vision transcription**: each page image read directly by Claude (vision) and transcribed into `hsk_data/transcripts/level{1,2,3}/page_NNN.md` — faithful, literal transcription: all hanzi, all pinyin with tone marks, all English, tables preserved as markdown, illustrations-that-are-content described in brackets, uncertain reads flagged `[UNCLEAR: ...]` rather than guessed silently. No summarizing, paraphrasing, or invented content — this is meant to be the grounding corpus for everything the downstream agent will ever state.
3. **Not yet done**: feeding these transcripts into `graphify` to build the knowledge graph, and building the retrieval/agent layer on top.

## Results

| Level | Total pages | Transcribed (full) | Skipped | 
|---|---|---|---|
| 1 | 142 | 136 | 6 |
| 2 | 151 | 141 | 10 |
| 3 | 207 | 201 | 6 |
| **Total** | **500** | **478** | **22** |

478 pages (95.6%) have complete faithful transcriptions. The 22 skipped pages are front-matter only — book covers, publisher credits, forewords/prefaces (序/前言), and "how to use this book" essays — none contain HSK vocabulary, grammar, or exam content.

### Skipped pages and reasons

| File | Reason |
|---|---|
| `level1/page_003.md` | Foreword page with a named official's handwritten signature/portrait |
| `level1/page_004.md` | Narrative preface essay (no tables) |
| `level1/page_005.md` | Preface / curriculum overview prose — skipped per explicit user instruction |
| `level1/page_006.md` | Preface prose — skipped per explicit user instruction |
| `level1/page_007.md` | Preface prose — skipped per explicit user instruction |
| `level1/page_008.md` | Narrative front-matter prose |
| `level2/page_003.md` | Front-matter page with a named individual's signature/portrait |
| `level2/page_004.md` | Front-matter page with a named individual's signature/portrait |
| `level2/page_005.md` | Preface essay (teaching philosophy/curriculum design), no tables |
| `level2/page_007.md` | Preface closing paragraph with author signature and date |
| `level2/page_008.md` | English preface text |
| `level2/page_010.md` | Preface continuation, ends with signature (Jiang Liping, Nov 2013) |
| `level2/page_011.md` | "本册说明" (About this volume) explanatory prose |
| `level2/page_012.md` | "本册说明" continuation |
| `level2/page_013.md` | "A Guide to the Use of This Book" (English) |
| `level2/page_014.md` | Front-matter introduction continuation |
| `level3/page_003.md` | Signature/portrait page |
| `level3/page_004.md` | Foreword/preface essay |
| `level3/page_005.md` | Preface prose — skipped per explicit user instruction |
| `level3/page_006.md` | Preface prose — skipped per explicit user instruction |
| `level3/page_007.md` | Preface prose — skipped per explicit user instruction |
| `level3/page_008.md` | Preface prose — skipped per explicit user instruction |

## Known issue: intermittent content-filter errors

Throughout transcription, subagents repeatedly hit `API Error: Output blocked by content filtering policy` on a subset of pages. Investigation during this session established:

- **Not about sensitive imagery.** Pages that failed were ordinary (publisher prefaces, stock photos including real public figures like Michael Jordan/Yao Ming, which transcribed fine elsewhere).
- **Not purely about output volume.** Some full 20-page batches completed with zero errors; some single-page attempts failed immediately.
- **Strong pattern:** failures clustered almost entirely on **dense multi-paragraph narrative prose** (forewords/prefaces/"about this textbook" essays) in the first ~20 pages of each book. Lesson content (dialogues, vocab tables, grammar notes, exercises) transcribed reliably across 470+ pages with essentially zero failures.
- **Best working hypothesis** (unconfirmed — inferred from behavior, not documented): a copyright-protection classifier on the API that's more sensitive to verbatim reproduction of expressive literary prose than to structured/tabular data, behaving probabilistically (the same page sometimes passed, sometimes didn't across repeated attempts).

**Resolution:** rather than fight the filter on content with zero HSK pedagogical value, these front-matter pages were marked `SKIPPED` with a one-line note instead of a full transcription. All actual teaching content was transcribed in full.

## File layout

```
hsk_data/
├── page_images/
│   ├── level1/page_001.png ... page_142.png
│   ├── level2/page_001.png ... page_151.png
│   ├── level3/page_001.png ... page_207.png
│   └── manifest.json
└── transcripts/
    ├── level1/page_001.md ... page_142.md
    ├── level2/page_001.md ... page_151.md
    └── level3/page_001.md ... page_207.md
```

## Next steps

1. Push repo (incl. Git-LFS-tracked PDFs) to GitHub — pending.
2. Run `graphify` over `hsk_data/transcripts/` to build the knowledge graph.
3. Build the retrieval/agent layer (strict citation, HSK-level-aware, "not found in materials" fallback) on top of the graph.
