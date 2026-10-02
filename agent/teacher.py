"""
Teacher mode: turn graph-located textbook pages into a structured lesson.

Shared by agent/cli.py and agent/server.py. The LLM writes the lesson, but
two grounding checks run in code afterwards rather than trusting the model
(small local models in particular don't reliably follow the prompt):

1. Every "(HSK Level N, page N)" citation in the answer is checked against
   the pages the model was actually given; any other citation is flagged.
2. The Teacher's note heading always carries "(not from the textbook)".
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from agent import prompts, retrieval
from agent.providers import get_provider

CITATION_RE = re.compile(r"\(HSK Level ([123]), page (\d+)\)")
TEACHER_NOTE_RE = re.compile(r"^(?P<prefix>[#*\s\d.]*)(?P<head>[^\n]*Teacher'?s note)(?P<rest>[^\n]*)$", re.IGNORECASE | re.MULTILINE)


@dataclass
class Lesson:
    question: str
    found: bool
    answer: str
    sources: list[str] = field(default_factory=list)
    pages_used: list[str] = field(default_factory=list)
    unverified_citations: list[str] = field(default_factory=list)
    provider_used: str | None = None
    context: str = ""


def _label_teacher_note(text: str) -> str:
    def fix(m: re.Match) -> str:
        line = m.group(0)
        if "not from the textbook" in line.lower():
            return line
        return f"{m.group('prefix')}{m.group('head')} (not from the textbook){m.group('rest')}"

    return TEACHER_NOTE_RE.sub(fix, text)


CJK_ONLY_RE = re.compile(r"[^一-鿿]")
SECTION_RE = re.compile(r"^[#*\s]*\d+\.\s")
CJK_SENTENCE_RE = re.compile(r"[一-鿿][一-鿿，、。？！：；…\s]{3,}")


def _citation_to_path(citation: str):
    m = CITATION_RE.fullmatch(citation)
    if not m:
        return None
    return retrieval.TRANSCRIPTS_DIR / f"level{m.group(1)}" / f"page_{int(m.group(2)):03d}.md"


PINYIN_AFTER_RE = re.compile(r"\s*[(（]\s*[A-Za-zāáǎàēéěèīíǐìōóǒòūúǔùǖǘǚǜüĀÁǍÀĒÉĚÈĪÍǏÌŌÓǑÒŪÚǓÙ]")


def _check_example_sentences(
    text: str, citations: list[str], carry: bool = True, examples_only: bool = False
) -> list[str]:
    """
    Verify that Chinese sentences presented under a textbook citation really
    appear on that page. Tracks the most recent citation within a section
    (citations often sit on their own line above the examples) and resets at
    each heading, so the teacher's own sentences in later sections aren't
    mistaken for claimed quotes.
    """
    page_text = {}
    for c in citations:
        path = _citation_to_path(c)
        if path and path.exists():
            page_text[c] = CJK_ONLY_RE.sub("", path.read_text(encoding="utf-8"))

    problems: list[str] = []
    current: str | None = None
    for line in text.splitlines():
        stripped = line.strip()
        if SECTION_RE.match(stripped) or "teacher's note" in stripped.lower() or "check yourself" in stripped.lower():
            current = None
        found = [f"(HSK Level {m.group(1)}, page {int(m.group(2))})" for m in CITATION_RE.finditer(line)]
        if found:
            current = found[-1]
        elif not carry:
            current = None
        if not current:
            continue
        for m in CJK_SENTENCE_RE.finditer(line):
            sentence = CJK_ONLY_RE.sub("", m.group(0))
            if len(sentence) < 4:
                continue
            # In chat the tutor writes explanatory prose in Chinese too; only
            # "hanzi (pinyin)" pairs are presented as quoted examples.
            if examples_only and not PINYIN_AFTER_RE.match(line, m.end()):
                continue
            if sentence in page_text.get(current, ""):
                continue
            elsewhere = [c for c, t in page_text.items() if sentence in t]
            shown = m.group(0).strip()
            if elsewhere:
                problems.append(f"「{shown}」 is cited as {current} but is actually on {elsewhere[0]}")
            else:
                problems.append(f"「{shown}」 (cited as {current}) does not appear in the textbook pages -- treat it as unverified")
    # de-duplicate, keep order
    return list(dict.fromkeys(problems))


def _check_citations(text: str, allowed: list[str]) -> list[str]:
    allowed_set = set(allowed)
    bad = []
    for m in CITATION_RE.finditer(text):
        cite = f"(HSK Level {m.group(1)}, page {int(m.group(2))})"
        if cite not in allowed_set and cite not in bad:
            bad.append(cite)
    return bad


def teach(question: str, *, provider_name: str | None = None, dfs: bool = False) -> Lesson:
    provider = get_provider(provider_name)
    if provider is None:
        raise RuntimeError("Teach mode needs an LLM provider -- set HSK_AGENT_PROVIDER (e.g. ollama).")

    terms = retrieval.key_terms(question)
    # Query the graph with just the Chinese terms when there are any -- English
    # filler like "teach me how to use" otherwise matches unrelated labels.
    graph_query = " ".join(terms) if terms else question
    result = retrieval.query(graph_query, dfs=dfs, budget=800)
    if result.error:
        raise RuntimeError(result.error)

    priority = retrieval.find_explanation_pages(terms)
    pages, citations = retrieval.load_source_pages(result, priority_pages=priority)

    if not pages and not result.found:
        return Lesson(question=question, found=False, answer=prompts.NOT_FOUND_MESSAGE)

    message = prompts.build_teacher_message(question, pages, result.raw_output if result.found else "")
    raw_answer = provider.complete(prompts.TEACHER_SYSTEM_PROMPT, message)

    answer = _label_teacher_note(raw_answer)
    unverified = _check_citations(answer, citations)
    sentence_problems = _check_example_sentences(answer, citations)
    warnings = []
    if unverified:
        warnings.append(
            "- " + ", ".join(unverified) + " "
            + ("was" if len(unverified) == 1 else "were")
            + " not among the textbook pages given to the teacher -- treat as unverified."
        )
    warnings.extend(f"- {p}" for p in sentence_problems)
    if warnings:
        answer += (
            "\n\n⚠️ Fact check (automatic, against the textbook transcripts):\n"
            + "\n".join(warnings)
            + "\nPages actually used for this lesson: " + ", ".join(citations) + "."
        )

    return Lesson(
        question=question,
        found=True,
        answer=answer,
        sources=citations,
        pages_used=citations,
        unverified_citations=unverified + sentence_problems,
        provider_used=provider.name,
        context=pages,
    )
