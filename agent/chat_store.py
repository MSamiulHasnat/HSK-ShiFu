"""
Persistent storage for tutor chat sessions (SQLite).

Keeps the tutor's chat history across server restarts so the UI can show a
list of past conversations, not just the one in progress. Runtime state only
(session_id, history, pinned topic pages) -- never mixed with the knowledge
graph itself.
"""

from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from pathlib import Path

DB_PATH = Path(__file__).resolve().parent / "data" / "chat_sessions.db"

_SCHEMA = """
CREATE TABLE IF NOT EXISTS sessions (
    id TEXT PRIMARY KEY,
    title TEXT NOT NULL,
    created_at REAL NOT NULL,
    last_active REAL NOT NULL,
    language TEXT,
    pages TEXT NOT NULL DEFAULT '',
    citations TEXT NOT NULL DEFAULT '[]',
    topic_terms TEXT NOT NULL DEFAULT '[]',
    history TEXT NOT NULL DEFAULT '[]'
)
"""


@contextmanager
def _connect():
    """A connection that commits on success and is always closed."""
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    try:
        with conn:
            conn.execute(_SCHEMA)
            columns = {row[1] for row in conn.execute("PRAGMA table_info(sessions)")}
            if "meta" not in columns:  # added later: topic label, focus, vocabulary entries in play
                conn.execute("ALTER TABLE sessions ADD COLUMN meta TEXT NOT NULL DEFAULT '{}'")
            yield conn
    finally:
        conn.close()


def save(data: dict) -> None:
    with _connect() as conn:
        conn.execute(
            """INSERT INTO sessions
                 (id, title, created_at, last_active, language, pages, citations, topic_terms, history, meta)
               VALUES (:id, :title, :created_at, :last_active, :language, :pages, :citations, :topic_terms,
                       :history, :meta)
               ON CONFLICT(id) DO UPDATE SET
                 title=:title, last_active=:last_active, language=:language,
                 pages=:pages, citations=:citations, topic_terms=:topic_terms, history=:history, meta=:meta""",
            {
                "id": data["id"],
                "title": data["title"],
                "created_at": data["created_at"],
                "last_active": data["last_active"],
                "language": data["language"],
                "pages": data["pages"],
                "citations": json.dumps(data["citations"]),
                "topic_terms": json.dumps(data["topic_terms"]),
                "history": json.dumps(data["history"]),
                "meta": json.dumps(data.get("meta") or {}),
            },
        )


def load(session_id: str) -> dict | None:
    with _connect() as conn:
        row = conn.execute(
            "SELECT id, title, created_at, last_active, language, pages, citations, topic_terms, history, meta "
            "FROM sessions WHERE id = ?",
            (session_id,),
        ).fetchone()
    if row is None:
        return None
    id_, title, created_at, last_active, language, pages, citations, topic_terms, history, meta = row
    return {
        "id": id_,
        "title": title,
        "created_at": created_at,
        "last_active": last_active,
        "language": language,
        "pages": pages,
        "citations": json.loads(citations),
        "topic_terms": json.loads(topic_terms),
        "history": json.loads(history),
        "meta": json.loads(meta or "{}"),
    }


def list_sessions(limit: int = 100) -> list[dict]:
    with _connect() as conn:
        rows = conn.execute(
            "SELECT id, title, created_at, last_active FROM sessions ORDER BY last_active DESC LIMIT ?",
            (limit,),
        ).fetchall()
    return [{"id": r[0], "title": r[1], "created_at": r[2], "last_active": r[3]} for r in rows]


def delete(session_id: str) -> None:
    with _connect() as conn:
        conn.execute("DELETE FROM sessions WHERE id = ?", (session_id,))
