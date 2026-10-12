"""
HTTP API for the study features: course browser, dictionary, flashcards,
drills, practice tests, progress and settings. Mounted by agent/server.py
under /api. None of these endpoints call an LLM -- answers come straight from
agent/course.py (the textbooks) and agent/progress.py (the student's record).
"""

from __future__ import annotations

import time
from typing import Literal, Optional

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from agent import course, lexicon, progress, quiz, srs
from agent.course_text import hanzi_forms, page_text, print_offset
from agent.retrieval import PROJECT_ROOT

router = APIRouter(prefix="/api", tags=["study"])
Level = Field(ge=1, le=3)
PAGE_IMAGES = PROJECT_ROOT / "hsk_data" / "page_images"


def _word(word_id: str) -> course.Word:
    w = course.load().words.get(word_id)
    if w is None:
        raise HTTPException(status_code=404, detail=f"No textbook word with id {word_id!r}.")
    return w


def _lesson(level: int, number: int) -> course.Lesson:
    lesson = course.load().lesson(level, number)
    if lesson is None:
        raise HTTPException(status_code=404, detail=f"HSK {level} has no lesson {number}.")
    return lesson


def _mastery(word_ids: list[str]) -> dict:
    counts = {"new": 0, "learning": 0, "young": 0, "mature": 0}
    for s in progress.word_status(word_ids).values():
        counts[s] += 1
    return {**counts, "total": len(word_ids)}


# ----------------------------------------------------------------------------
# Course and dictionary
# ----------------------------------------------------------------------------

@router.get("/course")
def course_map():
    data = course.load()
    return {"levels": [
        {"level": level, "lessons": [{**l.summary(), "mastery": _mastery(l.word_ids)} for l in data.lessons_for(level)]}
        for level in course.LEVELS
    ]}


@router.get("/course/{level}/{number}")
def lesson_detail(level: int, number: int):
    lesson = _lesson(level, number)
    data = course.load()
    status = progress.word_status(lesson.word_ids)
    words = [{**data.words[i].to_dict(), "status": status[i]} for i in lesson.word_ids]
    sentences = [s.to_dict() for s in data.sentences if s.level == level and s.lesson == number]
    return {**lesson.summary(), "words": words, "sentences": sentences, "mastery": _mastery(lesson.word_ids)}


@router.get("/lexicon")
def lexicon_index():
    """Compact word list for the browser: every written form -> word ids, plus each word's basics."""
    data = course.load()
    forms: dict[str, list[str]] = {}
    for w in data.words.values():
        for f in hanzi_forms(w.hanzi):
            if "…" not in f:
                forms.setdefault(f, []).append(w.id)
    return {"forms": forms,
            "words": {w.id: [w.hanzi, w.pinyin, w.meaning, w.level, w.lesson, w.pos] for w in data.words.values()}}


@router.get("/words/search")
def word_search(q: str = Query(min_length=1, max_length=40), limit: int = Query(30, ge=1, le=100)):
    results = lexicon.search(q, limit=limit)
    status = progress.word_status([w.id for w in results])
    return {"query": q, "results": [{**w.to_dict(), "status": status[w.id]} for w in results]}


@router.get("/words/{word_id}")
def word_detail(word_id: str):
    w = _word(word_id)
    card = progress.get_cards([w.id]).get(w.id)
    others = [o.to_dict() for o in lexicon.lookup(hanzi_forms(w.hanzi)[0]) if o.id != w.id]
    sentences = lexicon.sentences_with(w.hanzi, limit=8, prefer_level=w.level, prefer_lesson=w.lesson)
    lesson = course.load().lesson(w.level, w.lesson) if w.lesson else None
    return {
        **w.to_dict(),
        "status": srs.status(card),
        "card": card.to_dict() if card else None,
        "lesson_title": f"{lesson.title_zh} ({lesson.title_en})" if lesson else None,
        "sentences": [s.to_dict() for s in sentences],
        "other_entries": others,
    }


# ----------------------------------------------------------------------------
# Flashcards
# ----------------------------------------------------------------------------

@router.get("/review/queue")
def review_queue(limit: int = Query(20, ge=1, le=100), level: Optional[int] = Query(None, ge=1, le=3),
                 lesson: Optional[int] = Query(None, ge=1, le=20)):
    if lesson is not None and level is None:
        raise HTTPException(status_code=400, detail="Pass a level together with the lesson.")
    now = time.time()
    queue = progress.review_queue(limit=limit, level=level, lesson=lesson, now=now)
    cards = []
    for w in queue["words"]:
        card = queue["cards"].get(w.id)
        example = lexicon.sentences_with(w.hanzi, limit=1, prefer_level=w.level, prefer_lesson=w.lesson)
        cards.append({
            "word": w.to_dict(),
            "status": srs.status(card),
            "intervals": {str(g): s for g, s in srs.preview(card or srs.Card(), now).items()},
            "example": example[0].to_dict() if example else None,
        })
    return {"cards": cards, "counts": queue["counts"]}


class ReviewAnswer(BaseModel):
    word_id: str = Field(max_length=40)
    grade: int = Field(ge=1, le=4)


@router.post("/review/answer")
def review_answer(req: ReviewAnswer):
    _word(req.word_id)
    card = progress.answer_card(req.word_id, req.grade)
    return {"card": card.to_dict(), "status": srs.status(card), "due_in": card.due - time.time()}


class WordRef(BaseModel):
    word_id: str = Field(max_length=40)


@router.post("/review/add")
def review_add(req: WordRef):
    _word(req.word_id)
    card = progress.introduce(req.word_id)
    return {"status": srs.status(card)}


# ----------------------------------------------------------------------------
# Textbook pages (transcript + the scanned page itself), for checking citations
# ----------------------------------------------------------------------------

@router.get("/page/{level}/{page}")
def textbook_page(level: int, page: int):
    if level not in course.LEVELS:
        raise HTTPException(status_code=404, detail="Levels are 1-3.")
    text = page_text(level, page)
    if text is None:
        raise HTTPException(status_code=404, detail=f"No transcribed page {page} in HSK {level}.")
    lesson = next((l for l in course.load().lessons_for(level) if l.start_page <= page <= l.end_page), None)
    image = PAGE_IMAGES / f"level{level}" / f"page_{page:03d}.png"
    return {
        "level": level, "page": page, "citation": f"(HSK Level {level}, page {page})",
        "printed_page": page - print_offset(level),
        "lesson": lesson.summary() if lesson else None,
        "transcript": text,
        "image_url": f"/api/page/{level}/{page}/image" if image.exists() else None,
    }


@router.get("/page/{level}/{page}/image")
def textbook_page_image(level: int, page: int):
    image = PAGE_IMAGES / f"level{level}" / f"page_{page:03d}.png"  # ints only: no path tricks
    if level not in course.LEVELS or not image.exists():
        raise HTTPException(status_code=404, detail="No scanned image for that page.")
    return FileResponse(image, media_type="image/png", headers={"Cache-Control": "max-age=86400"})


# ----------------------------------------------------------------------------
# Drills and practice tests
# ----------------------------------------------------------------------------

@router.get("/drill")
def drill(level: int = Query(1, ge=1, le=3), lesson: Optional[int] = Query(None, ge=1, le=20),
          types: str = Query("", max_length=80), count: int = Query(10, ge=1, le=40),
          word_ids: str = Query("", max_length=2000)):
    ids = [i for i in word_ids.split(",") if i] or None
    kinds = [t for t in types.split(",") if t in quiz.TYPES] or None
    questions = quiz.drill(level, lesson=lesson, types=kinds, count=count, word_ids=ids)
    if not questions:
        raise HTTPException(status_code=404, detail="Couldn't build questions for that selection.")
    return {"questions": questions}


class DrillAnswer(BaseModel):
    word_id: str = Field(max_length=40)
    correct: bool
    mode: str = Field("drill", max_length=20)


@router.post("/drill/answer")
def drill_answer(req: DrillAnswer):
    _word(req.word_id)
    card = progress.record_drill(req.word_id, req.correct, req.mode)
    return {"status": srs.status(card)}


@router.get("/test/{level}")
def practice_test(level: int):
    if level not in course.LEVELS:
        raise HTTPException(status_code=404, detail="Practice tests exist for levels 1-3.")
    return quiz.practice_test(level)


class TestResult(BaseModel):
    level: int = Level
    score: int = Field(ge=0)
    total: int = Field(ge=1, le=200)
    seconds: Optional[int] = Field(None, ge=0)
    sections: dict = Field(default_factory=dict)


@router.post("/test/result")
def test_result(req: TestResult):
    if req.score > req.total:
        raise HTTPException(status_code=400, detail="Score can't exceed the total.")
    progress.save_test(req.level, req.score, req.total, req.seconds, req.sections)
    return {"ok": True, "history": progress.test_history(10)}


# ----------------------------------------------------------------------------
# Progress and settings
# ----------------------------------------------------------------------------

@router.get("/progress")
def progress_overview():
    return progress.stats()


class Settings(BaseModel):
    target_level: Optional[int] = Field(None, ge=1, le=3)
    daily_new: Optional[int] = Field(None, ge=0, le=100)


@router.get("/settings")
def get_settings():
    return progress.get_settings()


@router.post("/settings")
def update_settings(req: Settings):
    return progress.update_settings(req.model_dump(exclude_none=True))


class ResetRequest(BaseModel):
    confirm: Literal["RESET"]


@router.post("/progress/reset")
def reset_progress(req: ResetRequest):
    progress.reset_all()
    return {"ok": True}
