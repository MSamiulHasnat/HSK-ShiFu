"""
Which Chinese example sentences in a tutor reply really appear in the textbooks.

The tutor writes examples as 汉字 (pinyin). Small models sometimes present a
sentence of their own as if it were the book's (e.g. "here's the sentence
again: 我已经回家了" when the book says 王老师已经回家了). The citation fact check in
agent/teacher.py only covers sentences shown under a citation, so this check
looks up *every* such example across all transcribed pages and reports, for
each one, either the page it's printed on or that it's the tutor's own.
"""

from __future__ import annotations

import re
from functools import lru_cache

from agent.course import LEVELS
from agent.course_text import pages
from agent.teacher import CJK_SENTENCE_RE, PINYIN_AFTER_RE

CJK_ONLY_RE = re.compile(r"[^一-鿿]")
MIN_CHARS = 4


@lru_cache(maxsize=1)
def _book() -> list[tuple[int, int, str]]:
    return [(level, page, CJK_ONLY_RE.sub("", text)) for level in LEVELS for page, text in pages(level).items()]


NEGATIVE_RE = re.compile(r"mistake|not quite|incorrect|not correct|isn'?t (?:right|correct)|wrong|不对|错", re.IGNORECASE)
CORRECTION_RE = re.compile(r"correct|right (?:way|answer|sentence)|should be|正确|应该", re.IGNORECASE)


def contradicts_student(reply: str, student_message: str) -> bool:
    """
    True when the tutor calls the student's answer wrong but then gives the
    student's own sentence as the correction -- a self-contradiction small
    models produce ("there's a mistake... the correct sentence is: <same>").
    """
    answer = CJK_ONLY_RE.sub("", student_message)
    if len(answer) < MIN_CHARS or not NEGATIVE_RE.search(reply):
        return False
    for line in reply.splitlines():
        if not CORRECTION_RE.search(line):
            continue
        if any(CJK_ONLY_RE.sub("", m.group(0)) == answer for m in CJK_SENTENCE_RE.finditer(line)):
            return True
    return False


def check_examples(text: str, prefer: list[str] | None = None, exclude: str = "") -> list[dict]:
    """
    [{"text", "found", "citation"}] for each 汉字 (pinyin) example in `text`.
    `prefer`: citations to report first when a sentence is on several pages
    (the pages pinned for the topic). `exclude`: the student's own message --
    the tutor quoting it back isn't presenting an example.
    """
    excluded = CJK_ONLY_RE.sub("", exclude)
    preferred = prefer or []
    results: list[dict] = []
    seen: set[str] = set()
    for line in text.splitlines():
        for m in CJK_SENTENCE_RE.finditer(line):
            if not PINYIN_AFTER_RE.match(line, m.end()):
                continue
            shown = m.group(0).strip()
            tail = re.split(r"[：:]", shown)[-1].strip()  # drop a lead-in like "你说的是："
            if len(CJK_ONLY_RE.sub("", tail)) >= MIN_CHARS:
                shown = tail
            key = CJK_ONLY_RE.sub("", shown)
            if len(key) < MIN_CHARS or key in seen or (excluded and key in excluded):
                continue
            seen.add(key)
            hits = [f"(HSK Level {level}, page {page})" for level, page, body in _book() if key in body]
            hits.sort(key=lambda c: c not in preferred)
            results.append({"text": shown, "found": bool(hits), "citation": hits[0] if hits else None})
    return results
