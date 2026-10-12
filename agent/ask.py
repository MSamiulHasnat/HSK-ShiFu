"""
Token-cheap textbook lookups for AI coding assistants (Claude Code, Codex,
Copilot, Kimi, ...) used as the tutor.

Instead of reading the repository (the transcripts and the knowledge graph
are well over a million tokens), an assistant runs one command and gets back
a few hundred tokens of exactly what the books say, with page citations:

    python -m agent.ask context "What's the difference between 还是 and 或者?"
    python -m agent.ask word 已经
    python -m agent.ask search "already"
    python -m agent.ask lesson 2 4
    python -m agent.ask grammar 把
    python -m agent.ask page 2 47
    python -m agent.ask check "我已经回家了。(Wǒ yǐjīng huí jiā le.)"

The same functions back the MCP server (agent/mcp_server.py). No LLM, no
network; everything comes from agent/course.py and the transcripts.
"""

from __future__ import annotations

import argparse
import re
import sys

from agent import course, lexicon, retrieval, verify
from agent.course import GRAMMAR_HEAD_RE
from agent.course_text import CJK_RE, page_text

MAX_EXCERPT = 1800
MAX_CONTEXT = 6000
NOT_FOUND = "This isn't covered in the HSK textbook materials I have access to."


def _entry(w: course.Word) -> str:
    where = f"HSK {w.level}, Lesson {w.lesson}" if w.lesson else f"HSK {w.level}"
    kind = "" if w.kind == "core" else f" [{course.KIND_LABELS[w.kind]}]"
    return f"{w.hanzi} ({w.pinyin}) {w.pos} {w.meaning} — {where} {w.citation}{kind}"


def _sentence(s) -> str:
    extra = " | ".join(x for x in (s.pinyin, s.english) if x)
    return f"  · {s.text}" + (f"  ({extra})" if extra else "") + f" {s.citation}"


def word(query: str, sentences: int = 3) -> str:
    """Exact textbook entry (or closest matches) plus sentences that use it."""
    hits = lexicon.lookup(query) or lexicon.search(query, limit=5)
    if not hits:
        return NOT_FOUND
    out = []
    for w in hits[:5]:
        out.append(_entry(w))
        for s in lexicon.sentences_with(w.hanzi, limit=sentences, prefer_level=w.level, prefer_lesson=w.lesson):
            out.append(_sentence(s))
        sentences = 0 if len(hits) > 1 else sentences  # examples only for the best match
    return "\n".join(out)


def search(query: str, limit: int = 10) -> str:
    hits = lexicon.search(query, limit=limit)
    return "\n".join(_entry(w) for w in hits) if hits else NOT_FOUND


def lesson(level: int, number: int) -> str:
    les = course.load().lesson(level, number)
    if les is None:
        return f"HSK {level} has no lesson {number}."
    words = course.load().words
    lines = [f"HSK {level} Lesson {number}: {les.title_zh} ({les.title_pinyin}) — {les.title_en}; "
             f"pages {les.start_page}-{les.end_page}", "Words:"]
    lines += [f"  {_entry(words[i])}" for i in les.word_ids]
    lines.append("Grammar:")
    lines += [f"  {g.title} {g.citation}" for g in les.grammar] or ["  (none in this lesson)"]
    return "\n".join(lines)


def _excerpt(level: int, page: int, term: str) -> str:
    """The section of a page that starts at a heading mentioning `term`, else the page's start."""
    text = page_text(level, page) or ""
    lines = text.splitlines()
    start = next((i for i, l in enumerate(lines) if term in l and (l.lstrip().startswith("#")
                  or GRAMMAR_HEAD_RE.match(l.strip()))), 0)
    body = [lines[start]] if lines else []
    for line in lines[start + 1:]:
        if GRAMMAR_HEAD_RE.match(line.strip()) and CJK_RE.search(line) and term not in line:
            break
        body.append(line)
    chunk = "\n".join(l for l in body if l.strip() and not l.strip().startswith("[")).strip()
    return chunk[:MAX_EXCERPT] + (" …" if len(chunk) > MAX_EXCERPT else "")


def grammar(term: str, limit: int = 2) -> str:
    """Grammar points whose title mentions `term`, with the book's explanation text."""
    points = [g for l in course.load().lessons.values() for g in l.grammar if term in g.title]
    if not points:
        pages = retrieval.find_explanation_pages(retrieval.key_terms(term) or [term], limit=limit)
        if not pages:
            return NOT_FOUND
        out = []
        for p in pages:
            m = re.match(r"level(\d)/page_(\d+)", p)
            out.append(f"=== (HSK Level {m.group(1)}, page {int(m.group(2))}) ===\n"
                       f"{_excerpt(int(m.group(1)), int(m.group(2)), term)}")
        return "\n\n".join(out)
    out = [f"Grammar points mentioning {term}: " + "; ".join(f"HSK {g.level} L{g.lesson} {g.title} {g.citation}"
                                                          for g in points[:6])]
    for g in points[:limit]:
        out.append(f"=== {g.title} — HSK {g.level} Lesson {g.lesson} {g.citation} ===\n{_excerpt(g.level, g.page, term)}")
    return "\n\n".join(out)


def page(level: int, number: int) -> str:
    text = page_text(level, number)
    return text if text is not None else f"No transcribed page {number} in HSK {level}."


def context(question: str) -> str:
    """
    Everything needed to answer one HSK question from the books, in one call:
    lesson summary for "HSK N lesson M", otherwise the word entries and grammar
    explanations for the Chinese terms in the question. Capped at ~6k chars.
    """
    ref = lexicon.find_lesson_reference(question)
    if ref:
        return lesson(*ref)
    terms = retrieval.key_terms(question)
    if not terms:
        hits = lexicon.search(question, limit=5)
        return "\n".join(_entry(w) for w in hits) if hits else (
            NOT_FOUND + " (Tip: include the Chinese word or 'HSK N lesson M'.)")
    parts = []
    for t in terms[:4]:
        if lexicon.lookup(t):
            parts.append(word(t, sentences=2))
        g = grammar(t, limit=1)
        if g != NOT_FOUND:
            parts.append(g)
    text = "\n\n".join(dict.fromkeys(parts)) or NOT_FOUND
    return text[:MAX_CONTEXT] + ("\n… (truncated; ask about one term at a time for more)" if len(text) > MAX_CONTEXT else "")


def check(text: str) -> str:
    """Which 汉字 (pinyin) examples in `text` are printed in the textbooks."""
    results = verify.check_examples(text)
    if not results:
        return "No 汉字 (pinyin) examples of 4+ characters found to check."
    return "\n".join(f"{'✓' if r['found'] else '✗'} {r['text']} — "
                     + (f"in the textbook {r['citation']}" if r["found"] else "NOT in the textbook (label it as your own)")
                     for r in results)


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="python -m agent.ask", description="Cheap, cited HSK textbook lookups.")
    sub = p.add_subparsers(dest="cmd", required=True)
    for name in ("context", "word", "search", "grammar", "check"):
        sub.add_parser(name).add_argument("text", nargs="+")
    for name in ("lesson", "page"):
        sp = sub.add_parser(name)
        sp.add_argument("level", type=int)
        sp.add_argument("number", type=int)
    a = p.parse_args(argv)
    if a.cmd in ("lesson", "page"):
        out = (lesson if a.cmd == "lesson" else page)(a.level, a.number)
    else:
        out = {"context": context, "word": word, "search": search, "grammar": grammar, "check": check}[a.cmd](" ".join(a.text))
    sys.stdout.reconfigure(encoding="utf-8")
    print(out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
