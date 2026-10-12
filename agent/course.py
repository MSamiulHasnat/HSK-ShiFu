"""
The textbooks as structured, citable data.

Every vocabulary word, lesson, grammar point and example sentence is parsed
deterministically from the page transcriptions in hsk_data/transcripts -- no
LLM is involved anywhere in this module. It's what the study features
(dictionary, flashcards, drills, practice tests, the course browser) are built
on, and every item carries the page it came from, so anything shown to a
student can be traced back to the book.

Sources inside each book:
- the back-of-book vocabulary index (词语总表): word, pinyin, part of speech,
  meaning, lesson -- split into syllabus words (生词), proper nouns (专有名词),
  words outside the HSK syllabus (超纲词), and new words built from characters
  already learned (旧字新词);
- each lesson's numbered "New Words" lists, for the page a word is introduced on;
- the table of contents and each lesson's opening page, for lesson titles and
  page ranges;
- the "注释 Notes" sections, for grammar points;
- dialogue and example lines, for sentences that use each word.
"""

from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass, field
from functools import lru_cache

from agent.course_sentences import Sentence, extract_sentences, verify_pinyin
from agent.course_text import (CJK_RE, LATIN_RE, clean_cell, hanzi_forms, index_start, join_hanzi, pages,
                               print_offset)

LEVELS = (1, 2, 3)
KIND_ORDER = {"core": 0, "extra": 1, "compound": 2, "proper": 3}
KIND_LABELS = {
    "core": "HSK syllabus word",
    "extra": "Not in the HSK syllabus for this level",
    "compound": "New word built from characters already learned",
    "proper": "Proper noun",
}
CN_LEVEL = {"一级": 1, "二级": 2, "三级": 3, "四级": 4, "五级": 5, "六级": 6}



@dataclass
class Word:
    id: str
    hanzi: str
    pinyin: str
    pos: str
    meaning: str
    level: int
    lesson: int | None
    kind: str  # core | extra | compound | proper
    page: int | None = None  # PDF page where the lesson introduces it
    hsk_level: int | None = None  # official HSK level, when the book states it
    in_notes: bool = False  # taught in a lesson's notes rather than its word list
    order: int = 0  # position in the lesson's New Words list

    @property
    def citation(self) -> str:
        if self.page is None:
            return f"(HSK Level {self.level}, vocabulary index)"
        return f"(HSK Level {self.level}, page {self.page})"

    def to_dict(self) -> dict:
        return {
            "id": self.id, "hanzi": self.hanzi, "pinyin": self.pinyin, "pos": self.pos,
            "meaning": self.meaning, "level": self.level, "lesson": self.lesson, "kind": self.kind,
            "kind_label": KIND_LABELS[self.kind], "page": self.page, "hsk_level": self.hsk_level,
            "citation": self.citation,
        }


@dataclass
class GrammarPoint:
    title: str
    level: int
    lesson: int
    page: int

    @property
    def citation(self) -> str:
        return f"(HSK Level {self.level}, page {self.page})"

    def to_dict(self) -> dict:
        return {"title": self.title, "level": self.level, "lesson": self.lesson, "page": self.page,
                "citation": self.citation}


@dataclass
class Lesson:
    level: int
    number: int
    title_zh: str
    title_en: str
    title_pinyin: str
    start_page: int
    end_page: int
    grammar: list[GrammarPoint] = field(default_factory=list)
    word_ids: list[str] = field(default_factory=list)

    @property
    def key(self) -> str:
        return f"{self.level}-{self.number}"

    @property
    def pages(self) -> list[int]:
        return list(range(self.start_page, self.end_page + 1))

    def summary(self) -> dict:
        return {"key": self.key, "level": self.level, "number": self.number, "title_zh": self.title_zh,
                "title_en": self.title_en, "title_pinyin": self.title_pinyin, "start_page": self.start_page,
                "end_page": self.end_page, "word_count": len(self.word_ids),
                "grammar": [g.to_dict() for g in self.grammar]}


@dataclass
class Course:
    words: dict[str, Word]
    lessons: dict[str, Lesson]
    sentences: list[Sentence]

    def lesson(self, level: int, number: int) -> Lesson | None:
        return self.lessons.get(f"{level}-{number}")

    def lessons_for(self, level: int) -> list[Lesson]:
        return sorted((l for l in self.lessons.values() if l.level == level), key=lambda l: l.number)

    def words_for(self, level: int | None = None, lesson: int | None = None, kinds=("core",)) -> list[Word]:
        out = [w for w in self.words.values()
               if w.kind in kinds and (level is None or w.level == level) and (lesson is None or w.lesson == lesson)]
        return sorted(out, key=curriculum_key)


def curriculum_key(w: Word) -> tuple:
    return (w.level, w.lesson or 99, KIND_ORDER[w.kind], w.order or 999, w.pinyin)


# ----------------------------------------------------------------------------
# Vocabulary index
# ----------------------------------------------------------------------------

def _parse_index(level: int) -> list[Word]:
    words: list[Word] = []
    seen: Counter = Counter()
    section = None
    book = pages(level)
    for page in sorted(p for p in book if p >= index_start(level)):
        for line in book[page].splitlines():
            s = line.strip()
            if not s.startswith("|"):
                if "专有名词" in s:
                    section = "proper"
                elif "超纲词" in s:
                    section = "extra"
                elif "旧字新词" in s:
                    section = "compound"
                elif "生词" in s:
                    section = "core"
                continue
            cells = [c.strip() for c in s.strip("|").split("|")]
            first = clean_cell(cells[0]).lstrip("*").strip()
            if section is None or not CJK_RE.search(first) or re.search("词语|新词|词性|名词$", first):
                continue
            expected = {"core": 5, "proper": 4, "extra": 6, "compound": 6}[section]
            if len(cells) != expected:
                continue
            cells = [clean_cell(c) for c in cells]
            if section == "proper":
                pinyin, pos, meaning, lesson_cell = cells[1], "proper noun", cells[2], cells[3]
            else:
                pinyin, pos, meaning, lesson_cell = cells[1], cells[2], cells[3], cells[4]
            lm = re.match(r"(\d+)", lesson_cell)
            hsk_level = level if section == "core" else None
            if section == "extra":
                hsk_level = CN_LEVEL.get(cells[5].strip())
            seen[first] += 1
            wid = f"{level}:{first}" + (f"#{seen[first]}" if seen[first] > 1 else "")
            words.append(Word(
                id=wid, hanzi=first, pinyin=pinyin, pos=pos, meaning=meaning.strip("* "),
                level=level, lesson=int(lm.group(1)) if lm else None, kind=section,
                hsk_level=hsk_level, in_notes="notes" in lesson_cell.lower(),
            ))
    return words


# ----------------------------------------------------------------------------
# Lessons: table of contents, opening pages, grammar notes
# ----------------------------------------------------------------------------

TOC_NUM_RE = re.compile(r"^(\d{1,2})[\s　]+(.+)$")
GRAMMAR_ITEM_RE = re.compile(r"^\d+[.．]\s*")


def _parse_toc(level: int) -> dict[int, dict]:
    toc: dict[int, dict] = {}
    book = pages(level)
    for page in sorted(p for p in book if p < 25):
        for line in book[page].splitlines():
            s = line.strip()
            if not s.startswith("|") or "课文" in s:
                continue
            cells = [c.strip() for c in s.strip("|").split("|")]
            if cells and cells[0] == "":
                cells = cells[1:]
            if re.fullmatch(r"\d{1,2}", cells[0] or ""):
                number, rest = int(cells[0]), cells[1:]
            else:
                m = TOC_NUM_RE.match(cells[0])
                if not m:
                    continue
                number, rest = int(m.group(1)), [m.group(2)] + cells[1:]
            if len(rest) < 3 or not re.fullmatch(r"\d+", rest[1]):
                continue
            parts = re.split(r"<br>| / ", rest[0], maxsplit=1)
            grammar: list[str] = []
            if len(rest) > 3 and "(blank)" not in rest[3]:
                for piece in rest[3].split("<br>"):
                    piece = piece.strip()
                    if not piece:
                        continue
                    if GRAMMAR_ITEM_RE.match(piece) or not grammar:
                        grammar.append(GRAMMAR_ITEM_RE.sub("", piece))
                    else:
                        grammar[-1] += " — " + piece
            toc[number] = {
                "title_zh": parts[0].strip(), "title_en": parts[1].strip() if len(parts) > 1 else "",
                "printed": int(rest[1]), "grammar": grammar,
            }
    return toc


TITLE_SKIP = ("标准教程", "Standard Course", "热身", "Warm-up", "课文", "Lesson", "PDF page")


def _opening_title(text: str) -> tuple[str, str, str]:
    """
    (zh, pinyin, en) from a lesson's first page. The books print either a
    pinyin line, a hanzi line and an English line, or "14 Pinyin 汉字" as one
    heading followed by the English.
    """
    lines = []
    for raw in text.splitlines()[:24]:
        line = re.sub(r"^\d{1,2}\**[\s　]+", "", raw.strip().lstrip("#").strip().strip("*").strip())
        if line and not line.startswith("[") and not re.fullmatch(r"[\d\-—\s]+", line) \
                and not any(s in line for s in TITLE_SKIP):
            lines.append(line.strip("*").strip())
    for i, line in enumerate(lines):
        first_cjk = CJK_RE.search(line)
        if not first_cjk or len(CJK_RE.findall(line)) < 2:
            continue
        nxt = lines[i + 1] if i + 1 < len(lines) else ""
        en = nxt if LATIN_RE.search(nxt) and not CJK_RE.search(nxt) else ""
        head = line[:first_cjk.start()]
        if LATIN_RE.search(head):
            return join_hanzi(line[first_cjk.start():]), head.strip(" 　"), en
        if LATIN_RE.search(line):
            continue
        prev = lines[i - 1] if i else ""
        pinyin = prev if LATIN_RE.search(prev) and not CJK_RE.search(prev) else ""
        return join_hanzi(line), pinyin, en
    return "", "", ""


NOTES_START_RE = re.compile(r"^(注释|语法)")
NOTES_END_RE = re.compile(r"^(练习|Exercises|运用|Application|语音|Pronunciation|汉字|Characters|文化|Culture|热身)")
GRAMMAR_HEAD_RE = re.compile(r"^(?:#{1,4}\s*)?(?:\*\*)?([1-9])(?:\*\*)?[\s　]+(\S.{1,110})$")


def _scan_grammar(level: int, number: int, page_numbers: list[int]) -> list[GrammarPoint]:
    found: list[GrammarPoint] = []
    in_notes = False
    texts = pages(level)
    for page in page_numbers:
        for line in texts.get(page, "").splitlines():
            bare = line.strip().lstrip("#").strip().strip("*").strip()
            if NOTES_START_RE.match(bare):
                in_notes = True
                continue
            if NOTES_END_RE.match(bare):
                in_notes = False
                continue
            if not in_notes:
                continue
            m = GRAMMAR_HEAD_RE.match(line.strip())
            if m and CJK_RE.search(m.group(2)) and "___" not in line:
                title = m.group(2).replace("**", "").replace("　", " ").strip()
                found.append(GrammarPoint(title=title, level=level, lesson=number, page=page))
    return found


def _build_lessons(level: int, words: list[Word]) -> dict[int, Lesson]:
    book = pages(level)
    offset = print_offset(level)
    toc = _parse_toc(level)
    lesson_numbers = sorted({w.lesson for w in words if w.lesson})
    warmups = [p for p in sorted(book) if re.search(r"热身|Warm-up", book[p]) and p < index_start(level)]
    # Lessons without a warm-up are the early pinyin lessons, so warm-ups belong to the last N lessons.
    starts = dict(zip(lesson_numbers[-len(warmups):], warmups)) if warmups else {}
    for number, entry in toc.items():
        starts.setdefault(number, entry["printed"] + offset)
    ordered = sorted((n, p) for n, p in starts.items() if n in lesson_numbers)
    lessons: dict[int, Lesson] = {}
    for i, (number, start) in enumerate(ordered):
        end = ordered[i + 1][1] - 1 if i + 1 < len(ordered) else index_start(level) - 1
        zh, pinyin, en = _opening_title(book.get(start, ""))
        entry = toc.get(number, {})
        lesson = Lesson(level=level, number=number, title_zh=entry.get("title_zh") or zh,
                        title_en=entry.get("title_en") or en, title_pinyin=pinyin,
                        start_page=start, end_page=end)
        scanned = _scan_grammar(level, number, lesson.pages)
        if entry.get("grammar") and len(entry["grammar"]) == len(scanned):
            for g, title in zip(scanned, entry["grammar"]):
                g.title = title  # the contents page's bilingual wording is cleaner
        lesson.grammar = scanned
        lessons[number] = lesson
    return lessons


# ----------------------------------------------------------------------------
# Where each word is introduced
# ----------------------------------------------------------------------------

NEW_WORD_LINE_RE = re.compile(r"^[\s*•\-]*(\d{1,3})[.．]\s*\**([^\s　*|]+)")


def _locate_words(level: int, words: list[Word], lessons: dict[int, Lesson]) -> None:
    book = pages(level)
    listed: dict[tuple[int, str], tuple[int, int]] = {}  # (lesson, form) -> (page, number)
    for lesson in lessons.values():
        for page in lesson.pages:
            for line in book.get(page, "").splitlines():
                m = NEW_WORD_LINE_RE.match(line)
                if m and CJK_RE.search(m.group(2)):
                    for form in hanzi_forms(m.group(2)):
                        listed.setdefault((lesson.number, form), (page, int(m.group(1))))
    for w in words:
        lesson = lessons.get(w.lesson) if w.lesson else None
        if lesson is None:
            continue
        forms = hanzi_forms(w.hanzi)
        hit = next((listed[(w.lesson, f)] for f in forms if (w.lesson, f) in listed), None)
        if hit:
            w.page, w.order = hit
            continue
        # Notes-taught words and compounds: first lesson page that mentions the word.
        w.page = next((p for p in lesson.pages if any(f in book.get(p, "") for f in forms)), lesson.start_page)


# ----------------------------------------------------------------------------
# Build
# ----------------------------------------------------------------------------

@lru_cache(maxsize=1)
def load() -> Course:
    """Parse all three books once per process (about a quarter of a second)."""
    words: dict[str, Word] = {}
    lessons: dict[str, Lesson] = {}
    sentences: list[Sentence] = []
    for level in LEVELS:
        level_words = _parse_index(level)
        level_lessons = _build_lessons(level, level_words)
        _locate_words(level, level_words, level_lessons)
        for w in sorted(level_words, key=curriculum_key):
            words[w.id] = w
            if w.lesson in level_lessons:
                level_lessons[w.lesson].word_ids.append(w.id)
        for lesson in level_lessons.values():
            lessons[lesson.key] = lesson
        sentences.extend(extract_sentences(level, level_lessons))
    verify_pinyin(sentences, words.values())
    return Course(words=words, lessons=lessons, sentences=sentences)
