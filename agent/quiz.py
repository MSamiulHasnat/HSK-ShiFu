"""
Exam-style practice questions, generated deterministically from the
textbooks -- no LLM. Every correct answer is a book fact (a word's own
pinyin/meaning from the vocabulary lists, or a sentence exactly as printed),
and every question carries the page it came from.

Question types:
- meaning  看汉字选意思   hanzi -> pick the English meaning
- hanzi    看意思选汉字   English meaning -> pick the hanzi
- pinyin   选拼音        hanzi -> pick the pinyin (tones count)
- listen   听音选词      hear the word -> pick the hanzi
- cloze    选词填空      textbook sentence with a gap -> pick the word
- order    连词成句      textbook sentence in shuffled pieces -> put it back in order

Wrong options are other real book words, filtered so that none of them can
also be a right answer (no shared meanings, no identical pinyin, never the
same word).
"""

from __future__ import annotations

import random
import re

from agent import course, lexicon
from agent.course import Word
from agent.course_text import CJK_RE, hanzi_forms, strip_tones

TYPES = ("meaning", "hanzi", "pinyin", "listen", "cloze", "order")
STOPWORDS = {"to", "the", "a", "an", "of", "for", "and", "or", "be", "in", "on", "at", "with", "used",
             "sth", "sb", "one", "etc", "as", "is", "it", "by", "something", "somebody", "word"}

TEST_PLANS = {
    1: [("听力 Listening", "listen", 10), ("阅读 Reading", "meaning", 10), ("拼音 Pinyin", "pinyin", 5),
        ("选词填空 Fill in the blank", "cloze", 5)],
    2: [("听力 Listening", "listen", 10), ("阅读 Reading", "meaning", 5), ("选词填空 Fill in the blank", "cloze", 10),
        ("拼音 Pinyin", "pinyin", 5)],
    3: [("听力 Listening", "listen", 10), ("选词填空 Fill in the blank", "cloze", 10), ("阅读 Reading", "meaning", 5),
        ("书写 Sentence building", "order", 5)],
}
TEST_MINUTES = 25


def _meaning_tokens(meaning: str) -> set[str]:
    return {t for t in re.findall(r"[a-z]+", meaning.lower()) if t not in STOPWORDS and len(t) > 2}


def _distinct(answer: Word, other: Word) -> bool:
    """Could `other` never be mistaken for a correct answer about `answer`?"""
    if other.id == answer.id or set(hanzi_forms(other.hanzi)) & set(hanzi_forms(answer.hanzi)):
        return False
    if other.pinyin.lower().replace(" ", "") == answer.pinyin.lower().replace(" ", ""):
        return False
    if other.meaning.lower() == answer.meaning.lower():
        return False
    return not (_meaning_tokens(other.meaning) & _meaning_tokens(answer.meaning))


def _pool(level: int) -> list[Word]:
    return course.load().words_for(level=level)


def _pick_distractors(answer: Word, rng: random.Random, n: int = 3, prefer=None, key=None) -> list[Word]:
    """n distinct wrong options from the answer's level (falling back to all levels)."""
    for pool in (_pool(answer.level), [w for lv in course.LEVELS for w in _pool(lv)]):
        candidates = [w for w in pool if _distinct(answer, w)]
        if key:  # options must also look different from each other under this key
            seen = {key(answer)}
            unique = []
            for w in candidates:
                if key(w) not in seen:
                    seen.add(key(w))
                    unique.append(w)
            candidates = unique
        rng.shuffle(candidates)
        if prefer:
            candidates.sort(key=prefer)
        if len(candidates) >= n:
            return candidates[:n]
    return []


def _options(answer_label: dict, distractor_labels: list[dict], rng: random.Random) -> tuple[list[dict], int]:
    options = [answer_label] + distractor_labels
    order = list(range(len(options)))
    rng.shuffle(order)
    return [options[i] for i in order], order.index(0)


def _base(qtype: str, w: Word) -> dict:
    return {"type": qtype, "word": w.to_dict(), "citation": w.citation}


def meaning_question(w: Word, rng: random.Random) -> dict | None:
    wrong = _pick_distractors(w, rng, prefer=lambda o: o.pos != w.pos)
    if not wrong:
        return None
    options, answer = _options({"label": w.meaning}, [{"label": o.meaning} for o in wrong], rng)
    return {**_base("meaning", w), "prompt": {"hanzi": w.hanzi}, "instruction": "What does this word mean?",
            "options": options, "answer": answer}


def hanzi_question(w: Word, rng: random.Random) -> dict | None:
    wrong = _pick_distractors(w, rng, prefer=lambda o: (o.pos != w.pos, abs(len(o.hanzi) - len(w.hanzi))))
    if not wrong:
        return None
    options, answer = _options({"label": w.hanzi}, [{"label": o.hanzi} for o in wrong], rng)
    return {**_base("hanzi", w), "prompt": {"text": w.meaning, "pos": w.pos},
            "instruction": "Which word means this?", "options": options, "answer": answer}


def _sound_closeness(w: Word):
    target = strip_tones(w.pinyin)
    syllables = len(w.pinyin.split())

    def score(o: Word) -> tuple:
        p = strip_tones(o.pinyin)
        return (p != target, p[:2] != target[:2], len(o.pinyin.split()) != syllables, len(o.hanzi) != len(w.hanzi))

    return score


def pinyin_question(w: Word, rng: random.Random) -> dict | None:
    wrong = _pick_distractors(w, rng, prefer=_sound_closeness(w), key=lambda o: o.pinyin.lower())
    if not wrong:
        return None
    options, answer = _options({"label": w.pinyin}, [{"label": o.pinyin} for o in wrong], rng)
    return {**_base("pinyin", w), "prompt": {"hanzi": w.hanzi}, "instruction": "Pick the correct pinyin.",
            "options": options, "answer": answer}


def listen_question(w: Word, rng: random.Random) -> dict | None:
    wrong = _pick_distractors(w, rng, prefer=_sound_closeness(w))
    if not wrong:
        return None
    options, answer = _options({"label": w.hanzi}, [{"label": o.hanzi} for o in wrong], rng)
    return {**_base("listen", w), "prompt": {"audio": hanzi_forms(w.hanzi)[0]},
            "instruction": "Listen, then pick the word you heard.", "options": options, "answer": answer}


def _usable_sentence(w: Word, rng: random.Random, min_extra: int = 3):
    forms = [f for f in hanzi_forms(w.hanzi) if "…" not in f]
    if not forms:
        return None, None
    form = forms[0]
    candidates = [s for s in lexicon.sentences_with(w.hanzi, limit=12, prefer_level=w.level, prefer_lesson=w.lesson)
                  if s.text.count(form) == 1 and len(CJK_RE.findall(s.text)) >= len(form) + min_extra]
    if not candidates:
        return None, None
    return rng.choice(candidates[:4]), form


def cloze_question(w: Word, rng: random.Random) -> dict | None:
    sentence, form = _usable_sentence(w, rng)
    if not sentence:
        return None
    wrong = _pick_distractors(
        w, rng,
        prefer=lambda o: (o.pos == w.pos, abs(len(o.hanzi) - len(w.hanzi))),
        key=lambda o: hanzi_forms(o.hanzi)[0],
    )
    wrong = [o for o in wrong if hanzi_forms(o.hanzi)[0] not in sentence.text]
    if len(wrong) < 3:
        return None
    options, answer = _options({"label": form}, [{"label": hanzi_forms(o.hanzi)[0]} for o in wrong], rng)
    return {**_base("cloze", w), "prompt": {"before": sentence.text.split(form)[0],
                                            "after": sentence.text.split(form)[1]},
            "sentence": sentence.to_dict(), "citation": sentence.citation,
            "instruction": "Choose the word that fills the gap.", "options": options, "answer": answer}


def _tiles(text: str) -> list[str] | None:
    """Split a sentence into 3-6 pieces along book-word boundaries (punctuation stays attached)."""
    body = re.sub(r"[。？！?!…]+$", "", text)
    if not body or re.search(r"[A-Za-z0-9]", body):
        return None
    pieces: list[str] = []
    for chunk, _ in lexicon.segment(body):
        if pieces and not CJK_RE.search(chunk):
            pieces[-1] += chunk  # commas etc. ride along with the word before them
        else:
            pieces.append(chunk)
    while len(pieces) > 6:
        i = min(range(len(pieces) - 1), key=lambda k: len(pieces[k]) + len(pieces[k + 1]))
        pieces[i:i + 2] = [pieces[i] + pieces[i + 1]]
    return pieces if len(pieces) >= 3 else None


def order_question(w: Word, rng: random.Random) -> dict | None:
    sentence, _ = _usable_sentence(w, rng, min_extra=4)
    if not sentence or len(CJK_RE.findall(sentence.text)) > 16:
        return None
    tiles = _tiles(sentence.text)
    if not tiles or len(set(tiles)) < 3:
        return None
    shuffled = tiles[:]
    for _ in range(10):
        rng.shuffle(shuffled)
        if shuffled != tiles:
            break
    end = re.search(r"[。？！?!…]+$", sentence.text)
    return {**_base("order", w), "tiles": shuffled, "answer_tiles": tiles, "ending": end.group(0) if end else "",
            "sentence": sentence.to_dict(), "citation": sentence.citation,
            "instruction": "Put the pieces in order to make the textbook's sentence."}


BUILDERS = {"meaning": meaning_question, "hanzi": hanzi_question, "pinyin": pinyin_question,
            "listen": listen_question, "cloze": cloze_question, "order": order_question}


def build(words: list[Word], types: list[str], count: int, rng: random.Random) -> list[dict]:
    """Up to `count` questions, cycling through `types` over the given words."""
    types = [t for t in types if t in BUILDERS] or ["meaning"]
    pool = words[:]
    rng.shuffle(pool)
    questions: list[dict] = []
    used: set[str] = set()
    attempts = 0
    while len(questions) < count and attempts < count * 12 and pool:
        w = pool[attempts % len(pool)]
        qtype = types[len(questions) % len(types)] if len(types) > 1 else types[0]
        attempts += 1
        if (w.id, qtype) in used or (w.id in {q["word"]["id"] for q in questions} and len(pool) > count):
            continue
        q = BUILDERS[qtype](w, rng)
        if q:
            used.add((w.id, qtype))
            q["id"] = f"{qtype}-{w.id}-{len(questions)}"
            questions.append(q)
    return questions


def drill(level: int, lesson: int | None = None, types: list[str] | None = None, count: int = 10,
          word_ids: list[str] | None = None, seed: int | None = None) -> list[dict]:
    data = course.load()
    if word_ids:
        words = [data.words[i] for i in word_ids if i in data.words]
    else:
        words = data.words_for(level=level, lesson=lesson)
    return build(words, types or ["meaning", "listen", "pinyin", "cloze", "hanzi", "order"], count,
                 random.Random(seed))


def practice_test(level: int, seed: int | None = None) -> dict:
    rng = random.Random(seed)
    words = course.load().words_for(level=level)
    sections = []
    used: set[str] = set()
    for title, qtype, n in TEST_PLANS[level]:
        fresh = [w for w in words if w.id not in used]
        qs = build(fresh, [qtype], n, rng)
        used.update(q["word"]["id"] for q in qs)
        sections.append({"title": title, "type": qtype, "questions": qs})
    return {"level": level, "minutes": TEST_MINUTES, "sections": sections,
            "note": "Built from the textbook's own words and sentences. This is practice material, "
                    "not an official HSK paper."}
