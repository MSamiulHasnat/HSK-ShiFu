"""
Spaced-repetition scheduling for vocabulary cards (pure functions, no I/O).

An Anki-style SM-2 variant: a new card goes through short learning steps
(1 min, 10 min), graduates to day-based review intervals that grow by the
card's ease factor, and drops back to a relearning step when forgotten.

Grades: 1 = Again (forgot), 2 = Hard, 3 = Good, 4 = Easy.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass

DAY = 86400
LEARNING_STEPS = (60, 600)  # seconds
RELEARNING_STEPS = (600,)
GRADUATING_INTERVAL = 1.0  # days
EASY_INTERVAL = 4.0
START_EASE = 2.5
MIN_EASE = 1.3
MATURE_DAYS = 21
AGAIN, HARD, GOOD, EASY = 1, 2, 3, 4


@dataclass
class Card:
    state: str = "new"  # new | learning | review | relearning
    step: int = 0
    ease: float = START_EASE
    interval: float = 0.0  # days (review / relearning cards)
    due: float = 0.0  # unix time
    reps: int = 0
    lapses: int = 0
    last_review: float | None = None

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> "Card":
        return cls(**{k: data[k] for k in cls.__dataclass_fields__ if k in data})


def status(card: Card | None) -> str:
    """new | learning | young | mature -- the label shown to students."""
    if card is None or card.state == "new":
        return "new"
    if card.state in ("learning", "relearning"):
        return "learning"
    return "mature" if card.interval >= MATURE_DAYS else "young"


def schedule(card: Card, grade: int, now: float) -> Card:
    """Return the card's new state after answering it with `grade` at time `now`."""
    if grade not in (AGAIN, HARD, GOOD, EASY):
        raise ValueError(f"grade must be 1-4, got {grade!r}")
    c = Card(**asdict(card))
    c.reps += 1
    c.last_review = now

    if c.state in ("new", "learning", "relearning"):
        relearning = c.state == "relearning"
        steps = RELEARNING_STEPS if relearning else LEARNING_STEPS
        if c.state == "new":
            c.state, c.step = "learning", 0
        if grade == AGAIN:
            c.step = 0
            c.due = now + steps[0]
        elif grade == HARD:
            c.due = now + steps[min(c.step, len(steps) - 1)] * 1.5
        elif grade == GOOD and c.step + 1 < len(steps):
            c.step += 1
            c.due = now + steps[c.step]
        else:  # GOOD past the last step, or EASY: graduate
            if relearning:
                c.interval = max(1.0, c.interval) + (1.0 if grade == EASY else 0.0)
            else:
                c.interval = EASY_INTERVAL if grade == EASY else GRADUATING_INTERVAL
            if grade == EASY:
                c.ease += 0.15
            c.state, c.step = "review", 0
            c.due = now + c.interval * DAY
        return c

    # review card
    if grade == AGAIN:
        c.lapses += 1
        c.ease = max(MIN_EASE, c.ease - 0.2)
        c.interval = max(1.0, c.interval * 0.5)
        c.state, c.step = "relearning", 0
        c.due = now + RELEARNING_STEPS[0]
        return c
    if grade == HARD:
        c.ease = max(MIN_EASE, c.ease - 0.15)
        c.interval = max(c.interval + 1, c.interval * 1.2)
    elif grade == GOOD:
        c.interval = max(c.interval + 1, c.interval * c.ease)
    else:
        c.ease += 0.15
        c.interval = max(c.interval + 1, c.interval * c.ease * 1.3)
    c.due = now + c.interval * DAY
    return c


def preview(card: Card, now: float) -> dict[int, float]:
    """Seconds until the card would be due again, for each grade (for button labels)."""
    return {g: schedule(card, g, now).due - now for g in (AGAIN, HARD, GOOD, EASY)}


def quiz_grade(card: Card | None, correct: bool, now: float) -> int | None:
    """
    How a drill answer should move a card, or None to leave its schedule alone.
    Drills introduce new words and catch forgotten ones, but a correct answer
    to a card that isn't due yet doesn't count as an early review.
    """
    if not correct:
        return AGAIN
    if card is None or card.state == "new" or card.due <= now:
        return GOOD
    return None
