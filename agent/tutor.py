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

from agent import chat_store, prompts, retrieval
from agent.providers import get_provider
from agent.teacher import _check_citations, _check_example_sentences, _label_teacher_note

MAX_HISTORY_MESSAGES = 16
SESSION_TTL_SECONDS = 6 * 60 * 60
TOPIC_INTENT_RE = re.compile(
    r"teach|explain|what|how|why|mean|difference|learn|lesson|practice|quiz|"
    r"教|什么|怎么|为什么|意思|区别|学|练习|\?|？",
    re.IGNORECASE,
)
# Stricter signal used once a topic is already pinned: a practice answer can
# legitimately contain common words like "意思" or "什么" (e.g. "有意思" meaning
# "interesting") without the student asking to switch topics. Only an
# unambiguous new-topic request should replace the pinned material mid-exercise.
NEW_TOPIC_RE = re.compile(
    r"teach|explain|difference|what'?s|how (do|does|to)|learn|lesson|quiz|"
    r"教|讲讲|什么意思|什么是|区别|\?|？",
    re.IGNORECASE,
)


@dataclass
class TutorSession:
    id: str
    title: str = ""
    history: list[dict] = field(default_factory=list)
    pages: str = ""
    citations: list[str] = field(default_factory=list)
    topic_terms: list[str] = field(default_factory=list)
    language: str | None = None
    created_at: float = field(default_factory=time.time)
    last_active: float = field(default_factory=time.time)


SESSIONS: dict[str, TutorSession] = {}


def _to_dict(session: TutorSession) -> dict:
    return {
        "id": session.id,
        "title": session.title,
        "created_at": session.created_at,
        "last_active": session.last_active,
        "language": session.language,
        "pages": session.pages,
        "citations": session.citations,
        "topic_terms": session.topic_terms,
        "history": session.history,
    }


def _from_dict(data: dict) -> TutorSession:
    return TutorSession(
        id=data["id"],
        title=data["title"],
        history=data["history"],
        pages=data["pages"],
        citations=data["citations"],
        topic_terms=data["topic_terms"],
        language=data["language"],
        created_at=data["created_at"],
        last_active=data["last_active"],
    )


def _load_any(session_id: str) -> TutorSession | None:
    """Look up a session by id in the in-memory cache, else persisted storage."""
    if session_id in SESSIONS:
        return SESSIONS[session_id]
    data = chat_store.load(session_id)
    if data is None:
        return None
    session = _from_dict(data)
    SESSIONS[session.id] = session
    return session


def _get_session(session_id: str | None) -> TutorSession:
    now = time.time()
    for sid in [k for k, s in SESSIONS.items() if now - s.last_active > SESSION_TTL_SECONDS]:
        del SESSIONS[sid]
    session = _load_any(session_id) if session_id else None
    if session is None:
        session = TutorSession(id=session_id or uuid.uuid4().hex)
        SESSIONS[session.id] = session
    session.last_active = now
    return session


def reset(session_id: str) -> None:
    SESSIONS.pop(session_id, None)
    chat_store.delete(session_id)


def list_sessions() -> list[dict]:
    return chat_store.list_sessions()


def _format_reply(raw_reply: str, citations: list[str]) -> str:
    reply = _label_teacher_note(raw_reply)
    problems = [
        f"{c} was not among the textbook pages for this topic -- treat as unverified."
        for c in _check_citations(reply, citations)
    ] + _check_example_sentences(reply, citations, carry=False, examples_only=True)
    if problems:
        reply += "\n\n⚠️ Fact check (automatic, against the textbook transcripts):\n" + "\n".join(f"- {p}" for p in problems)
    return reply


def get_history_for_display(session_id: str) -> dict | None:
    session = _load_any(session_id)
    if session is None:
        return None
    history = [
        {"role": m["role"], "content": _format_reply(m["content"], session.citations) if m["role"] == "assistant" else m["content"]}
        for m in session.history
    ]
    return {"session_id": session.id, "title": session.title, "sources": session.citations, "history": history}


def _maybe_load_topic(session: TutorSession, message: str) -> bool:
    """Locate and pin textbook pages if this message starts a (new) topic."""
    terms = retrieval.key_terms(message)

    if session.pages:
        # A topic is already pinned -- only replace it on an unambiguous new-topic
        # request. A practice answer that happens to contain a common word like
        # "意思" or "什么" must NOT derail the material being taught.
        if not terms or not NEW_TOPIC_RE.search(message):
            return False
        new_terms = [t for t in terms if t not in session.topic_terms]
        if not new_terms:
            return False
        query = " ".join(terms)
    elif terms:
        query = " ".join(terms)
    elif TOPIC_INTENT_RE.search(message):
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
    if not session.title:
        session.title = message.strip()[:60] or "New conversation"

    session.history.append({"role": "user", "content": message})
    system = prompts.build_tutor_system_prompt(session.pages, session.language)
    raw_reply = provider.chat(system, _trimmed_history(session.history))
    thinking = provider.last_reasoning
    # Store the model's own words in history, not the fact-check block, so the
    # model doesn't start imitating the warnings in later turns.
    session.history.append({"role": "assistant", "content": raw_reply})
    chat_store.save(_to_dict(session))

    reply = _format_reply(raw_reply, session.citations)

    return {
        "session_id": session.id,
        "reply": reply,
        "sources": session.citations,
        "topic_changed": topic_changed,
        "thinking": thinking,
    }
