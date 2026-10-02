"""
Conversational tutor: a multi-turn chat where the tutor teaches in small
steps, asks one question at a time, evaluates the student's answers against
the textbook, and follows up.

Grounding works per *topic*, not per message: when the student asks to learn
something ("teach me 了", "what's the difference between 还是 and 或者?"), the
relevant textbook pages are located and pinned to the session. Ordinary
answers ("我把书放在桌子上了") don't trigger a new search -- otherwise every
Chinese word the student types would swap out the material being taught.

Each tutor reply goes through the same code-level fact checks as teach mode
(citations must be pages the tutor was given; Chinese example sentences shown
under a citation must appear on that page).
"""

from __future__ import annotations

import re
import time
import uuid
from dataclasses import dataclass, field

from agent import prompts, retrieval
from agent.providers import get_provider
from agent.teacher import _check_citations, _check_example_sentences, _label_teacher_note

MAX_HISTORY_MESSAGES = 16
SESSION_TTL_SECONDS = 6 * 60 * 60
TOPIC_INTENT_RE = re.compile(
    r"teach|explain|what|how|why|mean|difference|learn|lesson|practice|quiz|"
    r"教|什么|怎么|为什么|意思|区别|学|练习|\?|？",
    re.IGNORECASE,
)


@dataclass
class TutorSession:
    id: str
    history: list[dict] = field(default_factory=list)
    pages: str = ""
    citations: list[str] = field(default_factory=list)
    topic_terms: list[str] = field(default_factory=list)
    language: str | None = None
    last_active: float = field(default_factory=time.time)


SESSIONS: dict[str, TutorSession] = {}


def _get_session(session_id: str | None) -> TutorSession:
    now = time.time()
    for sid in [k for k, s in SESSIONS.items() if now - s.last_active > SESSION_TTL_SECONDS]:
        del SESSIONS[sid]
    if session_id and session_id in SESSIONS:
        session = SESSIONS[session_id]
    else:
        session = TutorSession(id=session_id or uuid.uuid4().hex)
        SESSIONS[session.id] = session
    session.last_active = now
    return session


def reset(session_id: str) -> None:
    SESSIONS.pop(session_id, None)


def _maybe_load_topic(session: TutorSession, message: str) -> bool:
    """Locate and pin textbook pages if this message starts a (new) topic."""
    terms = retrieval.key_terms(message)
    wants_topic = bool(TOPIC_INTENT_RE.search(message))

    if terms:
        new_terms = [t for t in terms if t not in session.topic_terms]
        if session.pages and not (new_terms and wants_topic):
            return False
        query = " ".join(terms)
    elif not session.pages and wants_topic:
        query = message  # e.g. "teach me the ba sentence" -- graph labels are bilingual
    else:
        return False

    result = retrieval.query(query, budget=800)
    if result.error:
        return False
    priority = retrieval.find_explanation_pages(terms)
    pages, citations = retrieval.load_source_pages(result, max_pages=3, max_chars=9000, priority_pages=priority)
    if not pages:
        return False
    session.pages, session.citations, session.topic_terms = pages, citations, terms
    return True


LATIN_RE = re.compile(r"[A-Za-z]")
CJK_CHAR_RE = re.compile(r"[一-鿿]")


def _detect_language(message: str) -> str | None:
    """
    Decide the explanation language from the student's message, once per
    session. Mostly-Latin text -> English; mostly-Chinese text -> Chinese.
    Later Chinese practice answers don't change it.
    """
    latin = len(LATIN_RE.findall(message))
    cjk = len(CJK_CHAR_RE.findall(message))
    if latin >= 4 and latin >= cjk:
        return "English"
    if cjk >= 4 and cjk > latin:
        return "Chinese (simplified)"
    return None


def _trimmed_history(history: list[dict]) -> list[dict]:
    recent = history[-MAX_HISTORY_MESSAGES:]
    while recent and recent[0]["role"] != "user":
        recent = recent[1:]
    return recent


def turn(session_id: str | None, message: str, provider_name: str | None = None) -> dict:
    provider = get_provider(provider_name)
    if provider is None:
        raise RuntimeError("The tutor needs an LLM provider -- set HSK_AGENT_PROVIDER (e.g. ollama).")

    session = _get_session(session_id)
    topic_changed = _maybe_load_topic(session, message)
    if session.language is None:
        session.language = _detect_language(message)

    session.history.append({"role": "user", "content": message})
    system = prompts.build_tutor_system_prompt(session.pages, session.language)
    raw_reply = provider.chat(system, _trimmed_history(session.history))
    # Store the model's own words in history, not the fact-check block, so the
    # model doesn't start imitating the warnings in later turns.
    session.history.append({"role": "assistant", "content": raw_reply})

    reply = _label_teacher_note(raw_reply)
    problems = [
        f"{c} was not among the textbook pages for this topic -- treat as unverified."
        for c in _check_citations(reply, session.citations)
    ] + _check_example_sentences(reply, session.citations, carry=False, examples_only=True)
    if problems:
        reply += "\n\n⚠️ Fact check (automatic, against the textbook transcripts):\n" + "\n".join(f"- {p}" for p in problems)

    return {
        "session_id": session.id,
        "reply": reply,
        "sources": session.citations,
        "topic_changed": topic_changed,
    }
