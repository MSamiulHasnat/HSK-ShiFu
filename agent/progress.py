"""
The student's learning record (SQLite, agent/data/progress.db): flashcard
schedules, every answer given in reviews and drills, practice-test results,
and settings. Single local learner -- this runs on the student's own machine.

Everything here is about the student, never about Chinese: word facts come
from agent/course.py.
"""

from __future__ import annotations

import json
import sqlite3
import time
from contextlib import contextmanager
from datetime import date, datetime, timedelta
from pathlib import Path

from agent import course, srs

DB_PATH = Path(__file__).resolve().parent / "data" / "progress.db"
DEFAULT_SETTINGS = {"target_level": 1, "daily_new": 15}
LEARN_AHEAD = 20 * 60  # learning cards this close to due count as due

_SCHEMA = """
CREATE TABLE IF NOT EXISTS cards (
    word_id TEXT PRIMARY KEY, state TEXT NOT NULL, step INTEGER NOT NULL, ease REAL NOT NULL,
    interval REAL NOT NULL, due REAL NOT NULL, reps INTEGER NOT NULL, lapses INTEGER NOT NULL,
    last_review REAL, introduced REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS answers (
    id INTEGER PRIMARY KEY AUTOINCREMENT, ts REAL NOT NULL, word_id TEXT NOT NULL,
    mode TEXT NOT NULL, grade INTEGER, correct INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS answers_ts ON answers (ts);
CREATE TABLE IF NOT EXISTS tests (
    id INTEGER PRIMARY KEY AUTOINCREMENT, ts REAL NOT NULL, level INTEGER NOT NULL,
    score INTEGER NOT NULL, total INTEGER NOT NULL, seconds INTEGER, sections TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT NOT NULL);
"""


@contextmanager
def _connect():
    """A connection that commits on success and is always closed."""
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    try:
        conn.executescript(_SCHEMA)
        with conn:
            yield conn
    finally:
        conn.close()


def _day_start(ts: float) -> float:
    d = datetime.fromtimestamp(ts)
    return datetime(d.year, d.month, d.day).timestamp()


# ----------------------------------------------------------------------------
# Settings
# ----------------------------------------------------------------------------

def get_settings() -> dict:
    with _connect() as conn:
        rows = dict(conn.execute("SELECT key, value FROM settings").fetchall())
    return {k: json.loads(rows[k]) if k in rows else v for k, v in DEFAULT_SETTINGS.items()}


def update_settings(changes: dict) -> dict:
    clean = {}
    if "target_level" in changes:
        clean["target_level"] = min(3, max(1, int(changes["target_level"])))
    if "daily_new" in changes:
        clean["daily_new"] = min(100, max(0, int(changes["daily_new"])))
    with _connect() as conn:
        for k, v in clean.items():
            conn.execute("INSERT INTO settings (key, value) VALUES (?, ?) "
                         "ON CONFLICT(key) DO UPDATE SET value = excluded.value", (k, json.dumps(v)))
    return get_settings()


# ----------------------------------------------------------------------------
# Cards
# ----------------------------------------------------------------------------

def _card_from_row(row) -> srs.Card:
    _, state, step, ease, interval, due, reps, lapses, last_review, _ = row
    return srs.Card(state=state, step=step, ease=ease, interval=interval, due=due, reps=reps,
                    lapses=lapses, last_review=last_review)


def get_cards(word_ids: list[str] | None = None) -> dict[str, srs.Card]:
    with _connect() as conn:
        if word_ids is None:
            rows = conn.execute("SELECT * FROM cards").fetchall()
        else:
            rows = []
            for i in range(0, len(word_ids), 500):
                chunk = word_ids[i:i + 500]
                rows += conn.execute(f"SELECT * FROM cards WHERE word_id IN ({','.join('?' * len(chunk))})",
                                     chunk).fetchall()
    return {r[0]: _card_from_row(r) for r in rows}


def _save_card(conn, word_id: str, card: srs.Card, now: float) -> None:
    conn.execute(
        """INSERT INTO cards (word_id, state, step, ease, interval, due, reps, lapses, last_review, introduced)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
           ON CONFLICT(word_id) DO UPDATE SET state=excluded.state, step=excluded.step, ease=excluded.ease,
             interval=excluded.interval, due=excluded.due, reps=excluded.reps, lapses=excluded.lapses,
             last_review=excluded.last_review""",
        (word_id, card.state, card.step, card.ease, card.interval, card.due, card.reps, card.lapses,
         card.last_review, now),
    )


def _check_word(word_id: str) -> None:
    if word_id not in course.load().words:
        raise KeyError(f"Unknown word id {word_id!r}")


def answer_card(word_id: str, grade: int, now: float | None = None) -> srs.Card:
    """A flashcard review: schedule the card and log the answer."""
    _check_word(word_id)
    now = now or time.time()
    card = get_cards([word_id]).get(word_id, srs.Card())
    new = srs.schedule(card, grade, now)
    with _connect() as conn:
        _save_card(conn, word_id, new, now)
        conn.execute("INSERT INTO answers (ts, word_id, mode, grade, correct) VALUES (?, ?, 'review', ?, ?)",
                     (now, word_id, grade, int(grade > srs.AGAIN)))
    return new


def record_drill(word_id: str, correct: bool, mode: str, now: float | None = None) -> srs.Card | None:
    """A drill / practice-test answer: always logged, moves the card only when it should."""
    _check_word(word_id)
    now = now or time.time()
    card = get_cards([word_id]).get(word_id)
    grade = srs.quiz_grade(card, correct, now)
    with _connect() as conn:
        conn.execute("INSERT INTO answers (ts, word_id, mode, grade, correct) VALUES (?, ?, ?, ?, ?)",
                     (now, word_id, mode[:20], grade, int(correct)))
        if grade is None:
            return card
        new = srs.schedule(card or srs.Card(), grade, now)
        _save_card(conn, word_id, new, now)
    return new


def introduce(word_id: str, now: float | None = None) -> srs.Card:
    """Put a word into the flashcard queue now (no-op if it's already being studied)."""
    _check_word(word_id)
    now = now or time.time()
    existing = get_cards([word_id]).get(word_id)
    if existing and existing.state != "new":
        return existing
    card = srs.Card(state="learning", step=0, due=now)
    with _connect() as conn:
        _save_card(conn, word_id, card, now)
    return card


def new_introduced_today(now: float | None = None) -> int:
    now = now or time.time()
    with _connect() as conn:
        return conn.execute("SELECT COUNT(*) FROM cards WHERE introduced >= ?", (_day_start(now),)).fetchone()[0]


def review_queue(limit: int = 20, level: int | None = None, lesson: int | None = None,
                 now: float | None = None) -> dict:
    """
    Cards to study now: due learning cards, then due reviews, then new words in
    textbook order. Without a lesson filter, new words come from levels up to
    the target level, capped by the daily allowance; picking a lesson means
    "teach me these words now", so its new words aren't capped.
    """
    now = now or time.time()
    settings = get_settings()
    data = course.load()
    if lesson is not None and level is not None:
        pool = data.words_for(level=level, lesson=lesson, kinds=tuple(course.KIND_ORDER))
    else:
        levels = [level] if level else list(range(1, settings["target_level"] + 1))
        pool = [w for lv in levels for w in data.words_for(level=lv)]
    cards = get_cards([w.id for w in pool])
    end_of_day = _day_start(now) + srs.DAY

    learning, reviews, new = [], [], []
    for w in pool:
        c = cards.get(w.id)
        if c is None or c.state == "new":
            new.append(w)
        elif c.state in ("learning", "relearning") and c.due <= now + LEARN_AHEAD:
            learning.append((c.due, w))
        elif c.state == "review" and c.due <= end_of_day:
            reviews.append((c.due, w))
    allowance = len(new) if lesson is not None else max(0, settings["daily_new"] - new_introduced_today(now))
    due_words = [w for _, w in sorted(learning, key=lambda t: t[0])] + [w for _, w in sorted(reviews, key=lambda t: t[0])]
    picked = (due_words + new[:allowance])[:limit]
    return {
        "words": picked,
        "cards": {w.id: cards.get(w.id) for w in picked},
        "counts": {"learning": len(learning), "review": len(reviews), "new": min(len(new), allowance),
                   "new_available": len(new)},
    }


def word_status(word_ids: list[str]) -> dict[str, str]:
    cards = get_cards(word_ids)
    return {wid: srs.status(cards.get(wid)) for wid in word_ids}


# ----------------------------------------------------------------------------
# Practice tests
# ----------------------------------------------------------------------------

def save_test(level: int, score: int, total: int, seconds: int | None, sections: dict) -> None:
    with _connect() as conn:
        conn.execute("INSERT INTO tests (ts, level, score, total, seconds, sections) VALUES (?, ?, ?, ?, ?, ?)",
                     (time.time(), level, score, total, seconds, json.dumps(sections)))


def test_history(limit: int = 20) -> list[dict]:
    with _connect() as conn:
        rows = conn.execute("SELECT ts, level, score, total, seconds, sections FROM tests ORDER BY ts DESC LIMIT ?",
                            (limit,)).fetchall()
    return [{"ts": r[0], "level": r[1], "score": r[2], "total": r[3], "seconds": r[4],
             "sections": json.loads(r[5])} for r in rows]


# ----------------------------------------------------------------------------
# Statistics
# ----------------------------------------------------------------------------

def weak_words(limit: int = 12, days: int = 30, now: float | None = None) -> list[dict]:
    """Words the student keeps getting wrong lately (wrong answers weigh more than right ones)."""
    now = now or time.time()
    with _connect() as conn:
        rows = conn.execute(
            "SELECT word_id, SUM(1 - correct), SUM(correct) FROM answers WHERE ts >= ? GROUP BY word_id",
            (now - days * srs.DAY,)).fetchall()
    cards = get_cards([r[0] for r in rows])
    words = course.load().words
    scored = []
    for wid, wrong, right in rows:
        if wid not in words or not wrong:
            continue
        card = cards.get(wid)
        score = wrong * 2 + (card.lapses if card else 0) - right * 0.75
        if score > 0:
            scored.append((score, wid, wrong, right))
    scored.sort(key=lambda t: -t[0])
    return [{**words[wid].to_dict(), "wrong": wrong, "right": right} for _, wid, wrong, right in scored[:limit]]


def _streak(active_days: set[date], today: date) -> int:
    day = today if today in active_days else today - timedelta(days=1)
    streak = 0
    while day in active_days:
        streak += 1
        day -= timedelta(days=1)
    return streak


def stats(now: float | None = None) -> dict:
    now = now or time.time()
    data = course.load()
    cards = get_cards()
    today = datetime.fromtimestamp(now).date()
    end_of_day = _day_start(now) + srs.DAY

    levels = []
    for level in course.LEVELS:
        syllabus = data.words_for(level=level)
        counts = {"new": 0, "learning": 0, "young": 0, "mature": 0}
        for w in syllabus:
            counts[srs.status(cards.get(w.id))] += 1
        levels.append({"level": level, "total": len(syllabus), **counts,
                       "known": counts["young"] + counts["mature"]})

    with _connect() as conn:
        rows = conn.execute("SELECT ts, correct, mode FROM answers WHERE ts >= ?",
                            (now - 60 * srs.DAY,)).fetchall()
    daily: dict[date, list[int]] = {}
    for ts, correct, _ in rows:
        daily.setdefault(datetime.fromtimestamp(ts).date(), []).append(correct)

    def accuracy(days: int) -> float | None:
        recent = [c for ts, c, _ in rows if ts >= now - days * srs.DAY]
        return round(sum(recent) / len(recent), 3) if recent else None

    activity = []
    for i in range(13, -1, -1):
        d = today - timedelta(days=i)
        answers = daily.get(d, [])
        activity.append({"date": d.isoformat(), "answers": len(answers), "correct": sum(answers)})

    due_now = sum(1 for c in cards.values()
                  if (c.state in ("learning", "relearning") and c.due <= now + LEARN_AHEAD)
                  or (c.state == "review" and c.due <= end_of_day))
    settings = get_settings()
    return {
        "settings": settings,
        "levels": levels,
        "due_now": due_now,
        "new_today": new_introduced_today(now),
        "new_left_today": max(0, settings["daily_new"] - new_introduced_today(now)),
        "answers_today": len(daily.get(today, [])),
        "streak": _streak(set(daily), today),
        "accuracy_7d": accuracy(7),
        "accuracy_30d": accuracy(30),
        "activity": activity,
        "weak_words": weak_words(8, now=now),
        "tests": test_history(5),
    }


def reset_all() -> None:
    """Erase the learning record (cards, answers, tests). Settings are kept."""
    with _connect() as conn:
        conn.execute("DELETE FROM cards")
        conn.execute("DELETE FROM answers")
        conn.execute("DELETE FROM tests")
