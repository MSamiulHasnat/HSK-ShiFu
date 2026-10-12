"""
Low-level helpers for reading the textbook transcriptions: page access,
hanzi/pinyin normalisation and pinyin syllable counting. Shared by
agent/course.py (words, lessons, grammar) and agent/course_sentences.py
(example sentences). Pure text processing -- no LLM, no network.
"""

from __future__ import annotations

import re
import unicodedata
from collections import Counter
from functools import lru_cache

from agent.retrieval import TRANSCRIPTS_DIR

CJK = "一-鿿"
CJK_RE = re.compile(f"[{CJK}]")
LATIN_RE = re.compile(r"[A-Za-z]")
HEADER_PAGE_RE = re.compile(r"printed page:\s*(\d+)")
SYLLABLE_RE = re.compile(
    r"(?:zh|ch|sh|[bpmfdtnlgkhjqxrzcsyw])?"
    r"(?:iang|iong|uang|ueng|uai|uan|van|ian|iao|ang|eng|ing|ong|ai|ei|ao|ou|an|en|in|un|vn"
    r"|ia|ie|iu|ua|uo|ui|ue|ve|er|a|o|e|i|u|v)"
    r"(?:r(?![aeiouv]))?"
)


def strip_tones(pinyin: str) -> str:
    """'Nǐ hǎo' -> 'nihao' (also drops spaces, apostrophes and tone numbers)."""
    return re.sub(r"[^a-z]", "", _toneless(pinyin))


def _toneless(pinyin: str) -> str:
    """Lowercase, tone marks removed, ü written as v (ǚ decomposes to u + two marks, so map it first)."""
    decomposed = unicodedata.normalize("NFD", pinyin.lower()).replace("ü", "v")
    return "".join(c for c in decomposed if not unicodedata.combining(c))


def hanzi_forms(hanzi: str) -> list[str]:
    """'秋（天）' -> ['秋天', '秋']; '南(方)' -> ['南方', '南']; '打篮球' -> ['打篮球']."""
    full = re.sub(r"[（）()]", "", hanzi)
    short = re.sub(r"[（(][^）)]*[）)]", "", hanzi)
    forms = [f for f in dict.fromkeys([full, short]) if f and CJK_RE.search(f)]
    return [re.sub(f"[^{CJK}…]", "", f) for f in forms]


def clean_cell(cell: str) -> str:
    """A markdown table cell as plain text (no <br>, bold, or italic wrapping)."""
    cell = cell.replace("<br>", " ").replace("**", "")
    cell = re.sub(r"^\*(.+)\*$", r"\1", cell.strip())
    return re.sub(r"\s+", " ", cell).strip()


def join_hanzi(text: str) -> str:
    """Level 2 prints dialogue with spaces between characters; remove them."""
    text = re.sub(f"(?<=[{CJK}，。？！、：；…])[ 　]+(?=[{CJK}，。？！、：；…“”])", "", text)
    return text.strip()


def pinyin_syllables(pinyin: str) -> int | None:
    """Count syllables in a pinyin line, or None if it isn't parseable as pinyin."""
    plain = _toneless(pinyin)
    count = 0
    for token in re.findall(r"[a-z]+", plain):
        pos = 0
        while pos < len(token):
            m = SYLLABLE_RE.match(token, pos)
            if not m or m.end() == pos:
                return None
            pos = m.end()
            count += 1
    return count or None


def page_text(level: int, page: int) -> str | None:
    """A transcribed page, or None if it's missing or was skipped (front matter)."""
    path = TRANSCRIPTS_DIR / f"level{level}" / f"page_{page:03d}.md"
    if not path.exists():
        return None
    text = path.read_text(encoding="utf-8")
    return None if "SKIPPED:" in text[:300] else text


@lru_cache(maxsize=None)
def pages(level: int) -> dict[int, str]:
    """{PDF page number: transcription} for every real page of one book."""
    out = {}
    for path in sorted((TRANSCRIPTS_DIR / f"level{level}").glob("page_*.md")):
        number = int(path.stem.split("_")[1])
        text = page_text(level, number)
        if text is not None:
            out[number] = text
    return out


def print_offset(level: int) -> int:
    """PDF page minus printed page number -- constant within each book."""
    diffs: Counter = Counter()
    for number, text in pages(level).items():
        m = HEADER_PAGE_RE.search(text[:300])
        if m:
            diffs[number - int(m.group(1))] += 1
    return diffs.most_common(1)[0][0]


def index_start(level: int) -> int:
    """First page of the back-of-book vocabulary index (词语总表)."""
    book = pages(level)
    half = max(book) // 2
    return min(p for p, t in book.items() if p > half and ("词语总表" in t or "课号" in t))
