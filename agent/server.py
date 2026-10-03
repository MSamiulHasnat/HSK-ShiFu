"""
Local web server for the HSK knowledge agent.

Run:
    python -m agent.server
    # or: uvicorn agent.server:app --reload --port 8000

Endpoints:
    GET  /           chat UI with the tutor (agent/static/index.html)
    POST /chat       {"message": "...", "session_id": null}
                      -> {"session_id", "reply", "sources", "topic_changed"}
                      multi-turn tutoring; pass back session_id to continue
    POST /chat/reset {"session_id": "..."} -- delete a conversation
    GET  /chat/sessions         list past conversations (id, title, timestamps)
    GET  /chat/sessions/{id}    full history for one conversation, for resuming it
    POST /ask        {"question": "...", "dfs": false, "budget": 2000, "provider": null}
                      -> {"question", "found", "answer", "sources", "provider_used", "raw_context"}
    GET  /graph/info  basic stats about the loaded graph (node/edge/community counts)
    GET  /healthz     liveness check
    GET  /docs        FastAPI's auto-generated interactive API docs
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse
from pydantic import BaseModel

from agent import prompts, retrieval, teacher, tutor
from agent.providers import get_provider

app = FastAPI(
    title="HSK Knowledge Agent",
    description="Graph-grounded HSK Q&A. Answers are pulled only from graphify-out/graph.json.",
    version="1.0.0",
)


class AskRequest(BaseModel):
    question: str
    dfs: bool = False
    budget: int = 2000
    provider: Optional[str] = None
    mode: str = "answer"  # "answer" (short cited answer) or "teach" (structured lesson)


class AskResponse(BaseModel):
    question: str
    found: bool
    answer: str
    sources: list[str]
    provider_used: Optional[str]
    raw_context: str


class ChatRequest(BaseModel):
    message: str
    session_id: Optional[str] = None
    provider: Optional[str] = None


class ChatResponse(BaseModel):
    session_id: str
    reply: str
    sources: list[str]
    topic_changed: bool
    thinking: Optional[str] = None


class ResetRequest(BaseModel):
    session_id: str


STATIC_DIR = Path(__file__).resolve().parent / "static"


@app.post("/chat", response_model=ChatResponse)
def chat(req: ChatRequest):
    if not req.message.strip():
        raise HTTPException(status_code=400, detail="Empty message.")
    try:
        return tutor.turn(req.session_id, req.message, provider_name=req.provider)
    except RuntimeError as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.post("/chat/reset")
def chat_reset(req: ResetRequest):
    tutor.reset(req.session_id)
    return {"ok": True}


@app.get("/chat/sessions")
def chat_sessions():
    return tutor.list_sessions()


@app.get("/chat/sessions/{session_id}")
def chat_session(session_id: str):
    data = tutor.get_history_for_display(session_id)
    if data is None:
        raise HTTPException(status_code=404, detail="Session not found.")
    return data


@app.get("/", response_class=HTMLResponse)
def index():
    return (STATIC_DIR / "index.html").read_text(encoding="utf-8")


@app.get("/healthz")
def healthz():
    return {"status": "ok", "graph_loaded": retrieval.graph_exists()}


@app.get("/graph/info")
def graph_info():
    path = retrieval.GRAPH_PATH
    if not path.exists():
        raise HTTPException(status_code=404, detail="No graph built yet. See INGESTION_REPORT.md.")
    data = json.loads(path.read_text(encoding="utf-8"))
    return {
        "nodes": len(data.get("nodes", [])),
        "edges": len(data.get("links", data.get("edges", []))),
        "hyperedges": len(data.get("hyperedges", [])),
        "path": str(path),
    }


@app.post("/ask", response_model=AskResponse)
def ask(req: AskRequest):
    if req.mode == "teach":
        try:
            lesson = teacher.teach(req.question, provider_name=req.provider, dfs=req.dfs)
        except RuntimeError as e:
            raise HTTPException(status_code=400, detail=str(e))
        return AskResponse(
            question=req.question,
            found=lesson.found,
            answer=lesson.answer,
            sources=lesson.sources,
            provider_used=lesson.provider_used,
            raw_context=lesson.context,
        )

    result = retrieval.query(req.question, dfs=req.dfs, budget=req.budget)

    if result.error:
        raise HTTPException(status_code=500, detail=result.error)

    sources = sorted({result.citation_for(n) for n in result.nodes})

    if not result.found:
        return AskResponse(
            question=req.question,
            found=False,
            answer=prompts.NOT_FOUND_MESSAGE,
            sources=[],
            provider_used=None,
            raw_context=result.raw_output,
        )

    provider = get_provider(req.provider)
    if provider is None:
        return AskResponse(
            question=req.question,
            found=True,
            answer=(
                "No LLM provider configured on the server (set HSK_AGENT_PROVIDER once one is "
                "implemented in agent/providers.py). Returning the raw retrieved graph context instead."
            ),
            sources=sources,
            provider_used=None,
            raw_context=result.raw_output,
        )

    user_message = prompts.build_user_message(req.question, result.raw_output)
    answer_text = provider.complete(prompts.SYSTEM_PROMPT, user_message)
    return AskResponse(
        question=req.question,
        found=True,
        answer=answer_text,
        sources=sources,
        provider_used=provider.name,
        raw_context=result.raw_output,
    )


def main():
    import uvicorn

    uvicorn.run("agent.server:app", host="127.0.0.1", port=8000, reload=False)


if __name__ == "__main__":
    main()
