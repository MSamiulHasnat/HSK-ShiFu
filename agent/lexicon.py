"""
Looking things up in the textbooks' vocabulary: exact lookup, search by
hanzi / pinyin / English, textbook sentences that use a word, splitting
Chinese text into book words, and spotting lesson references like
"HSK 2 lesson 5". Built on agent/course.py; no LLM involved.
"""

from __future__ import annotations

import re
from functools import lru_cache

from agent.course import KIND_ORDER, Course, Word, curriculum_key, load
from agent.course_sentences import Sentence
from agent.course_text import CJK_RE, hanzi_forms, strip_tones


def lookup(hanzi: str, course: Course | None = None) -> list[Word]:
    """Every book entry whose written form matches exactly (a word can appear at several levels)."""
    course = course or load()
    return sorted((w for w in course.words.values() if hanzi in hanzi_forms(w.hanzi) or w.hanzi == hanzi),
                  key=lambda w: (KIND_ORDER[w.kind], w.level))


def search(query: str, limit: int = 30, course: Course | None = None) -> list[Word]:
    course = course or load()
    q = query.strip()
    if not q:
        return []
    q_lower = q.lower()
    q_pinyin = strip_tones(q) if not CJK_RE.search(q) else ""
    scored: list[tuple[int, tuple, Word]] = []
    for w in course.words.values():
        forms = hanzi_forms(w.hanzi)
        score = 0
        if CJK_RE.search(q):
            if q in forms:
                score = 100
            elif any(f.startswith(q) for f in forms):
                score = 80
            elif any(q in f for f in forms):
                score = 60
            elif all(ch in w.hanzi for ch in q):
                score = 20
        else:
            p = strip_tones(w.pinyin)
            meaning = w.meaning.lower()
            if q_pinyin and p == q_pinyin:
                score = 90
            elif q_pinyin and len(q_pinyin) >= 2 and p.startswith(q_pinyin):
                score = 70
            if re.search(rf"(^|[^a-z]){re.escape(q_lower)}($|[^a-z])", meaning):
                score = max(score, 65 if meaning.startswith(("to " + q_lower, q_lower)) else 50)
            elif len(q_lower) >= 3 and q_lower in meaning:
                score = max(score, 30)
        if score:
            scored.append((score, curriculum_key(w), w))
    scored.sort(key=lambda t: (-t[0], KIND_ORDER[t[2].kind], t[1]))
    return [w for _, _, w in scored[:limit]]


def sentences_with(hanzi: str, limit: int = 6, prefer_level: int | None = None,
                   prefer_lesson: int | None = None, course: Course | None = None) -> list[Sentence]:
    """Textbook sentences containing the word, its own lesson's sentences first."""
    course = course or load()
    forms = hanzi_forms(hanzi) or [hanzi]
    hits = [s for s in course.sentences if any(f in s.text for f in forms)]
    hits.sort(key=lambda s: (
        not (s.level == prefer_level and s.lesson == prefer_lesson),
        s.level != prefer_level,
        s.english is None,
        len(s.text),
    ))
    return hits[:limit]


@lru_cache(maxsize=1)
def _form_index() -> tuple[dict[str, list[str]], int]:
    index: dict[str, list[str]] = {}
    for w in load().words.values():
        for form in hanzi_forms(w.hanzi):
            if "…" not in form:
                index.setdefault(form, []).append(w.id)
    return index, max(len(f) for f in index)


def segment(text: str) -> list[tuple[str, list[str]]]:
    """
    Greedy longest-match split of text into book words. Returns
    [(chunk, [word ids])] -- ids are empty for characters that aren't a book
    word on their own (and for non-Chinese text).
    """
    index, longest = _form_index()
    out: list[tuple[str, list[str]]] = []
    i = 0
    while i < len(text):
        if not CJK_RE.match(text[i]):
            j = i
            while j < len(text) and not CJK_RE.match(text[j]):
                j += 1
            out.append((text[i:j], []))
            i = j
            continue
        for size in range(min(longest, len(text) - i), 0, -1):
            chunk = text[i:i + size]
            if chunk in index:
                out.append((chunk, index[chunk]))
                i += size
                break
        else:
            out.append((text[i], []))
            i += 1
    return out


def words_in(text: str) -> list[Word]:
    """Distinct book words found in a piece of text, in order of appearance."""
    course = load()
    found: dict[str, Word] = {}
    for _, ids in segment(text):
        if ids:
            w = course.words[sorted(ids, key=lambda i: (KIND_ORDER[course.words[i].kind], course.words[i].level))[0]]
            found.setdefault(w.hanzi, w)
    return list(found.values())


def find_lesson_reference(text: str) -> tuple[int, int] | None:
    """'HSK 2 lesson 5', 'level 3, lesson 12', 'L1 lesson 4', '第五课' (needs a level) -> (level, lesson)."""
    m = re.search(r"(?:hsk|level|l)\s*([123])\D{0,12}?(?:lesson|课|第)\s*(\d{1,2})", text, re.IGNORECASE)
    if not m:
        m2 = re.search(r"(?:lesson|第)\s*(\d{1,2})\D{0,12}?(?:hsk|level)\s*([123])", text, re.IGNORECASE)
        if not m2:
            return None
        level, number = int(m2.group(2)), int(m2.group(1))
    else:
        level, number = int(m.group(1)), int(m.group(2))
    return (level, number) if load().lesson(level, number) else None
