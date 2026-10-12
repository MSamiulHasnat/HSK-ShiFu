"""
Example sentences from the textbooks: dialogue lines and grammar examples,
each with the page it's printed on, plus the book's own pinyin and English
when they can be attached with certainty.

Attaching is deliberately conservative -- a sentence with no pinyin is fine,
a sentence with somebody else's pinyin is a factual error:
- pinyin comes from the line printed directly above, and is kept only if the
  book's own pinyin for the words in the sentence appears in it;
- English comes from the "English Version" block that follows a dialogue, and
  is attached only when the dialogue's turns and the translation's lines
  match one to one, to turns that are a single line long.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from agent.course_text import CJK, CJK_RE, LATIN_RE, hanzi_forms, join_hanzi, pages, pinyin_syllables, strip_tones

SPEAKER = f"(?:[A-Z]|[{CJK}　 ]{{1,5}})[:：]"
TURN_START_RE = re.compile(f"^(?:例如[:：]\\s*)?{SPEAKER}")
PREFIX_RE = re.compile(
    f"^(?:例如[:：]\\s*)?(?:[（(]\\d+[)）]\\s*|[①-⑳❶-❿➀-➉]\\s*)?(?:{SPEAKER}\\s*)?"
)
ENGLISH_SPEAKER_RE = re.compile(r"^([A-Z]|[A-Z][a-z]+(?: [A-Z][a-z]+)?)[:：]\s*(.+)$")
FINAL_PUNCT_RE = re.compile(r"[。？！?!…]$")
PINYIN_LINE_RE = re.compile(
    r"^[A-Za-zāáǎàēéěèīíǐìōóǒòūúǔùǖǘǚǜüÁÀĀǍÉÈĒĚÍÌĪǏÓÒŌǑÚÙŪǓ\s,.?!'’，。？！:：\-…“”\"()（）]+$"
)
EXERCISE_MARKS = ("___", "＿", "…………", "/", "（　", "(  ", "（ ）", "( )")
# Phrases that only occur in exercise instructions ("两人一组…", "根据图片…"), not in example sentences.
INSTRUCTION_MARKS = ("一组", "根据", "说一说", "下面的", "选择", "填空", "图片", "朗读", "课文", "进行")


@dataclass
class Sentence:
    text: str
    level: int
    lesson: int | None
    page: int
    pinyin: str | None = None
    english: str | None = None

    @property
    def citation(self) -> str:
        return f"(HSK Level {self.level}, page {self.page})"

    def to_dict(self) -> dict:
        return {"text": self.text, "pinyin": self.pinyin, "english": self.english, "level": self.level,
                "lesson": self.lesson, "page": self.page, "citation": self.citation}


def _syllables_fit(pinyin: str, hanzi: str) -> bool:
    syllables = pinyin_syllables(pinyin)
    chars = len(CJK_RE.findall(hanzi))
    return syllables is not None and chars - hanzi.count("儿") <= syllables <= chars


def _clean(line: str) -> str:
    text = PREFIX_RE.sub("", line).strip()
    text = re.sub(r"[（(]=[^）)]*[）)]|[①-⑳]", "", text)
    return join_hanzi(text.replace("**", ""))


def _is_sentence(text: str) -> bool:
    return not (LATIN_RE.search(text) or len(CJK_RE.findall(text)) < 4 or len(text) > 70
                or not FINAL_PUNCT_RE.search(text) or re.search('["“”]', text)
                or any(mark in text for mark in INSTRUCTION_MARKS))


def _pair_english(turns: list[dict], english: list[str]) -> None:
    if not turns or len(turns) != len(english):
        return
    for turn, en in zip(turns, english):
        if turn["lines"] == 1 and len(turn["sentences"]) == 1:
            turn["sentences"][0].english = en


def extract_sentences(level: int, lessons) -> list[Sentence]:
    """`lessons`: {number: Lesson}; each needs `.number` and `.pages`."""
    out: list[Sentence] = []
    seen: set[str] = set()
    book = pages(level)
    for lesson in lessons.values():
        for page in lesson.pages:
            turns: list[dict] = []  # one per speaker turn: hanzi line count + stored sentences
            english: list[str] = []
            english_mode = False
            prev = ""
            for raw in book.get(page, "").splitlines():
                line = raw.strip()
                if not line:
                    continue
                if "English Version" in line:
                    english_mode, english = True, []
                    continue
                if english_mode:
                    m = ENGLISH_SPEAKER_RE.match(line.strip("*"))
                    if m and not CJK_RE.search(line):
                        english.append(m.group(2).strip())
                        continue
                    _pair_english(turns, english)
                    english_mode, turns = False, []
                if line.startswith("#"):
                    turns = []  # a new text block starts
                    prev = line
                    continue
                if line.startswith(("|", "[", "!")) or any(mark in line for mark in EXERCISE_MARKS):
                    prev = line
                    continue
                text = _clean(line)
                is_hanzi_line = bool(CJK_RE.search(text)) and not LATIN_RE.search(text)
                if is_hanzi_line and TURN_START_RE.match(line):
                    turns.append({"lines": 1, "sentences": []})
                elif is_hanzi_line and turns:
                    turns[-1]["lines"] += 1  # the same speaker continues on the next line
                if not _is_sentence(text):
                    prev = line
                    continue
                pinyin = prev if PINYIN_LINE_RE.match(prev) and _syllables_fit(prev, text) else None
                sentence = Sentence(text=text, level=level, lesson=lesson.number, page=page, pinyin=pinyin)
                if turns and is_hanzi_line:
                    turns[-1]["sentences"].append(sentence)
                prev = line
                if text not in seen:
                    seen.add(text)
                    out.append(sentence)
            if english_mode:
                _pair_english(turns, english)
    return out


def verify_pinyin(sentences: list[Sentence], words) -> None:
    """
    Keep a sentence's pinyin only if the book's own pinyin for the words in it
    shows up in that line (tones ignored) -- the line above a sentence is
    occasionally the pinyin of a different exercise item, and a syllable count
    alone can match by coincidence. `words`: iterable of Word.
    """
    by_form: dict[str, str] = {}
    for w in words:
        for form in hanzi_forms(w.hanzi):
            by_form.setdefault(form, strip_tones(w.pinyin))
    longest = max(len(f) for f in by_form)
    for s in sentences:
        if not s.pinyin:
            continue
        line = strip_tones(s.pinyin)
        checked = matched = 0
        i = 0
        while i < len(s.text):
            for size in range(min(longest, len(s.text) - i), 0, -1):
                form = s.text[i:i + size]
                if form in by_form:
                    checked += 1
                    matched += by_form[form] in line
                    i += size
                    break
            else:
                i += 1
        if checked == 0 or matched / checked < 0.75:
            s.pinyin = None
