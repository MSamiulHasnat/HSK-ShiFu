"""
Conversational tutor: a multi-turn chat where the tutor teaches in small
steps, asks one question at a time, evaluates the student's answers against
the textbook, and follows up.

Grounding works per *topic*, not per message: when the student asks to learn
something ("teach me 了", "HSK 2 lesson 5", or a study button in the web UI),
the relevant textbook pages are located and pinned to the session, together
with the exact word-list entries for the words in play. Ordinary answers
("我把书放在桌子上了") don't trigger a new search -- otherwise every Chinese word
the student types would swap out the material being taught.

A topic can come from:
- an explicit `focus` sent by the UI: a lesson, a grammar point, a word, or a
  review of the student's weak words (from agent/progress.py);
- a lesson reference in the message ("HSK 2 lesson 5", "level 3 lesson 12");
- otherwise the Chinese terms in the message, searched in the graph and the
  transcripts (agent/retrieval.py).

Each tutor reply goes through the same code-level fact checks as teach mode
(citations must be pages the tutor was given; Chinese example sentences shown
under a citation must appear on that page).
"""

from __future__ import annotations

import re
import time
import uuid
from collections.abc import Iterator
from dataclasses import dataclass, field

from agent import chat_store, course, lexicon, progress, prompts, retrieval, verify
from agent.providers import Provider, get_provider
from agent.teacher import _check_citations, _check_example_sentences, _label_teacher_note

MAX_HISTORY_MESSAGES = 16
SESSION_TTL_SECONDS = 6 * 60 * 60
TOPIC_PAGES, TOPIC_CHARS = 3, 9000
LESSON_PAGES, LESSON_CHARS = 4, 12000
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
    meta: dict = field(default_factory=dict)  # topic label, focus, vocabulary word ids


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
        "meta": session.meta,
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
        meta=data.get("meta") or {},
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


def _format_reply(raw_reply: str, citations: list[str], student_message: str = "") -> str:
    reply = _label_teacher_note(raw_reply)
    problems = [
        f"{c} was not among the textbook pages for this topic -- treat as unverified."
        for c in _check_citations(reply, citations)
    ] + _check_example_sentences(reply, citations, carry=False, examples_only=True)
    if student_message and verify.contradicts_student(reply, student_message):
        problems.append("王老师 said your answer has a mistake, but the \"correct\" sentence given is identical to "
                        "yours -- your answer matches it. Ask 王老师 to check again if you're unsure.")
    if problems:
        reply += "\n\n⚠️ Fact check (automatic, against the textbook transcripts):\n" + "\n".join(f"- {p}" for p in problems)
    return reply


def get_history_for_display(session_id: str) -> dict | None:
    session = _load_any(session_id)
    if session is None:
        return None
    history = []
    for i, m in enumerate(session.history):
        if m["role"] != "assistant":
            history.append({"role": m["role"], "content": m["content"]})
            continue
        asked = session.history[i - 1]["content"] if i else ""
        history.append({"role": "assistant", "content": _format_reply(m["content"], session.citations, asked),
                        "checks": verify.check_examples(m["content"], session.citations, exclude=asked)})
    return {"session_id": session.id, "title": session.title, "sources": session.citations,
            "topic": session.meta.get("topic"), "history": history}


# ----------------------------------------------------------------------------
# Choosing what the tutor teaches from
# ----------------------------------------------------------------------------

def _page_paths(level: int, pages: list[int]) -> list[str]:
    return [f"level{level}/page_{p:03d}.md" for p in dict.fromkeys(pages)]


def _vocab_line(w: course.Word) -> str:
    where = f"HSK Level {w.level}, Lesson {w.lesson}" if w.lesson else f"HSK Level {w.level}"
    return f"{w.hanzi} ({w.pinyin}) {w.pos} {w.meaning} — {where} {w.citation}"


def _lesson_topic(level: int, number: int) -> tuple[list[str], list[str], str] | None:
    lesson = course.load().lesson(level, number)
    if lesson is None:
        return None
    texts = retrieval.TRANSCRIPTS_DIR
    words = course.load().words
    word_pages = {words[i].page for i in lesson.word_ids if words[i].order}  # pages with a New Words list
    grammar_pages = {g.page for g in lesson.grammar}
    # The dialogues (where the new words are listed) and the grammar notes teach the most.
    ranked = [p for p in lesson.pages if p in word_pages] + [p for p in lesson.pages if p in grammar_pages]
    paths = [p for p in _page_paths(level, ranked or lesson.pages) if (texts / p).exists()]
    label = f"HSK {level} · Lesson {number} · {lesson.title_zh} ({lesson.title_en})"
    return paths, list(lesson.word_ids), label


def _focus_topic(focus: dict) -> tuple[list[str], list[str], str] | None:
    """(page paths, vocabulary word ids, label) for a study focus chosen in the UI."""
    data = course.load()
    kind = focus.get("type")
    if kind == "lesson":
        return _lesson_topic(int(focus["level"]), int(focus["lesson"]))
    if kind == "grammar":
        level, number, page = int(focus["level"]), int(focus["lesson"]), int(focus["page"])
        lesson = data.lesson(level, number)
        if lesson is None:
            return None
        first_text = min((data.words[i].page for i in lesson.word_ids if data.words[i].page), default=lesson.start_page)
        title = next((g.title for g in lesson.grammar if g.page == page), "grammar point")
        pages = [page, page + 1] if page + 1 <= lesson.end_page else [page]
        return _page_paths(level, pages + [first_text]), [], f"HSK {level} · Lesson {number} · {title}"
    if kind == "word":
        w = data.words.get(focus.get("id", ""))
        if w is None or w.page is None:
            return None
        pages = [(w.level, w.page)] + [(s.level, s.page) for s in lexicon.sentences_with(
            w.hanzi, limit=3, prefer_level=w.level, prefer_lesson=w.lesson)]
        paths = list(dict.fromkeys(f"level{lv}/page_{p:03d}.md" for lv, p in pages))
        return paths, [w.id], f"Word · {w.hanzi} ({w.pinyin})"
    if kind == "review":
        ids = [i for i in focus.get("word_ids") or [] if i in data.words]
        if not ids:
            ids = [w["id"] for w in progress.weak_words(8)]
        if not ids:
            return None
        words = [data.words[i] for i in ids[:8]]
        paths = list(dict.fromkeys(f"level{w.level}/page_{w.page:03d}.md" for w in words if w.page))
        return paths, [w.id for w in words], "Review · " + "、".join(w.hanzi for w in words)
    return None


def _pin(session: TutorSession, paths: list[str], vocab_ids: list[str], label: str | None,
         terms: list[str], max_pages: int, max_chars: int) -> bool:
    empty = retrieval.RetrievalResult(question="", found=False)
    pages, citations = retrieval.load_source_pages(empty, max_pages=max_pages, max_chars=max_chars,
                                                   priority_pages=paths)
    if not pages:
        return False
    words = course.load().words
    vocab_cites = [words[i].citation for i in vocab_ids if i in words and words[i].page]
    session.pages, session.topic_terms = pages, terms
    session.citations = list(dict.fromkeys(citations + vocab_cites))
    session.meta = {**session.meta, "topic": label, "vocab": vocab_ids}
    return True


def _maybe_load_topic(session: TutorSession, message: str, focus: dict | None = None) -> bool:
    """Locate and pin textbook pages if this message starts a (new) topic."""
    if focus:
        found = _focus_topic(focus)
        if found:
            paths, vocab_ids, label = found
            many = focus.get("type") in ("lesson", "review")
            return _pin(session, paths, vocab_ids, label, [],
                        LESSON_PAGES if many else TOPIC_PAGES, LESSON_CHARS if many else TOPIC_CHARS)

    ref = lexicon.find_lesson_reference(message)
    current = session.meta.get("topic") or ""
    if ref and not current.startswith(f"HSK {ref[0]} · Lesson {ref[1]} ·"):
        found = _lesson_topic(*ref)
        if found:
            return _pin(session, found[0], found[1], found[2], [], LESSON_PAGES, LESSON_CHARS)

    terms = retrieval.key_terms(message)
    if session.pages:
        # A topic is already pinned -- only replace it on an unambiguous new-topic
        # request. A practice answer that happens to contain a common word like
        # "意思" or "什么" must NOT derail the material being taught.
        if not terms or not NEW_TOPIC_RE.search(message):
            return False
        if not [t for t in terms if t not in session.topic_terms]:
            return False
        query = " ".join(terms)
    elif terms:
        query = " ".join(terms)
    elif TOPIC_INTENT_RE.search(message):
        query = message  # e.g. "teach me the ba sentence" -- graph labels are bilingual
    else:
        return False

    priority = retrieval.find_explanation_pages(terms)
    if len(priority) >= TOPIC_PAGES:
        # The pages that explain the term already fill the topic; the graph search
        # (a ~1.4s subprocess) would only add pages that don't fit.
        result = retrieval.RetrievalResult(question=query, found=False)
    else:
        result = retrieval.query(query, budget=800)
        if result.error:
            return False
    pages, citations = retrieval.load_source_pages(result, max_pages=TOPIC_PAGES, max_chars=TOPIC_CHARS,
                                                   priority_pages=priority)
    if not pages:
        return False
    # Exact word-list entries only for terms that are themselves book words
    # (not the pieces of a pattern name like 把字句).
    vocab = [w for t in terms for w in lexicon.lookup(t)][:8]
    words = course.load().words
    session.pages, session.topic_terms = pages, terms
    session.citations = list(dict.fromkeys(citations + [w.citation for w in vocab if w.page]))
    session.meta = {**session.meta, "topic": "、".join(terms) if terms else message.strip()[:40],
                    "vocab": [w.id for w in vocab if w.id in words]}
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


def _system_prompt(session: TutorSession) -> str:
    words = course.load().words
    vocab = [_vocab_line(words[i]) for i in session.meta.get("vocab", []) if i in words]
    return prompts.build_tutor_system_prompt(session.pages, session.language, vocabulary=vocab,
                                             target_level=progress.get_settings()["target_level"])


def _prepare(session_id: str | None, message: str, provider_name: str | None,
             focus: dict | None) -> tuple[Provider, TutorSession, bool]:
    provider = get_provider(provider_name)
    if provider is None:
        raise RuntimeError("The tutor needs an LLM provider -- set HSK_AGENT_PROVIDER (e.g. ollama).")
    session = _get_session(session_id)
    topic_changed = _maybe_load_topic(session, message, focus)
    if session.language is None:
        session.language = _detect_language(message)
    if not session.title:
        session.title = (session.meta.get("topic") if focus else None) or message.strip()[:60] or "New conversation"
    session.history.append({"role": "user", "content": message})
    return provider, session, topic_changed


def _finish(session: TutorSession, raw_reply: str) -> str:
    # Store the model's own words in history, not the fact-check block, so the
    # model doesn't start imitating the warnings in later turns.
    session.history.append({"role": "assistant", "content": raw_reply})
    chat_store.save(_to_dict(session))
    asked = session.history[-2]["content"] if len(session.history) >= 2 else ""
    return _format_reply(raw_reply, session.citations, asked)


def turn(session_id: str | None, message: str, provider_name: str | None = None,
         focus: dict | None = None) -> dict:
    provider, session, topic_changed = _prepare(session_id, message, provider_name, focus)
    try:
        raw_reply = provider.chat(_system_prompt(session), _trimmed_history(session.history))
    except Exception:
        session.history.pop()  # let the student simply resend
        raise
    reply = _finish(session, raw_reply)
    return {
        "session_id": session.id,
        "reply": reply,
        "sources": session.citations,
        "topic_changed": topic_changed,
        "topic": session.meta.get("topic"),
        "thinking": provider.last_reasoning,
        "checks": verify.check_examples(raw_reply, session.citations, exclude=message),
    }


def turn_stream(session_id: str | None, message: str, provider_name: str | None = None,
                focus: dict | None = None) -> Iterator[dict]:
    """
    The same turn as `turn()`, as events: one "meta" (session + sources), then
    "thinking" / "delta" chunks as the model writes, then "done" with the
    fact-checked reply -- or "error".
    """
    try:
        provider, session, topic_changed = _prepare(session_id, message, provider_name, focus)
    except (RuntimeError, ValueError) as e:
        yield {"event": "error", "detail": str(e)}
        return
    yield {"event": "meta", "session_id": session.id, "sources": session.citations,
           "topic_changed": topic_changed, "topic": session.meta.get("topic"), "title": session.title}
    parts: list[str] = []
    try:
        for kind, chunk in provider.stream(_system_prompt(session), _trimmed_history(session.history)):
            if kind == "text":
                parts.append(chunk)
                yield {"event": "delta", "text": chunk}
            else:
                yield {"event": "thinking", "text": chunk}
    except (RuntimeError, ValueError) as e:
        session.history.pop()
        yield {"event": "error", "detail": str(e)}
        return
    raw_reply = "".join(parts)
    reply = _finish(session, raw_reply)
    yield {"event": "done", "session_id": session.id, "reply": reply, "sources": session.citations,
           "topic": session.meta.get("topic"), "thinking": provider.last_reasoning,
           "checks": verify.check_examples(raw_reply, session.citations, exclude=message),
           "provider": getattr(provider, "used", None) or provider.name}
