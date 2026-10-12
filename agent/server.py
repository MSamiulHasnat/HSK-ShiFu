"""
Local web server for the HSK knowledge agent.

Run:
    python -m agent.server
    # or: uvicorn agent.server:app --reload --port 8000

Endpoints:
    GET  /           the study app (agent/static/): today, tutor, course, review, practice, dictionary
    GET  /api/...    study features -- course, words, flashcards, drills, tests, progress
                      (agent/api_study.py; no LLM involved)
    GET  /api/status which LLM provider/model the tutor is using
    POST /chat       {"message": "...", "session_id": null, "focus": null}
                      -> {"session_id", "reply", "sources", "topic_changed", "topic"}
                      multi-turn tutoring; pass back session_id to continue
    POST /chat/stream same body; Server-Sent Events: meta, thinking, delta, done | error
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
import os
from pathlib import Path
from typing import Literal, Optional

from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from agent import api_study, prompts, retrieval, teacher, tutor
from agent.providers import get_provider

app = FastAPI(
    title="HSK Knowledge Agent",
    description="Graph-grounded HSK Q&A. Answers are pulled only from graphify-out/graph.json.",
    version="2.0.0",
)
app.include_router(api_study.router)


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


class Focus(BaseModel):
    """What to study, chosen in the UI: a lesson, a grammar point, a word, or a review of weak words."""
    type: Literal["lesson", "grammar", "word", "review"]
    level: Optional[int] = Field(None, ge=1, le=3)
    lesson: Optional[int] = Field(None, ge=1, le=20)
    page: Optional[int] = Field(None, ge=1, le=300)
    id: Optional[str] = Field(None, max_length=40)
    word_ids: Optional[list[str]] = Field(None, max_length=20)


class ChatRequest(BaseModel):
    message: str = Field(max_length=4000)
    session_id: Optional[str] = Field(None, max_length=64)
    provider: Optional[str] = None
    focus: Optional[Focus] = None


class ChatResponse(BaseModel):
    session_id: str
    reply: str
    sources: list[str]
    topic_changed: bool
    topic: Optional[str] = None
    thinking: Optional[str] = None
    checks: list[dict] = []


class ResetRequest(BaseModel):
    session_id: str


STATIC_DIR = Path(__file__).resolve().parent / "static"
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


def _focus(req: ChatRequest) -> Optional[dict]:
    return req.focus.model_dump(exclude_none=True) if req.focus else None


@app.post("/chat", response_model=ChatResponse)
def chat(req: ChatRequest):
    if not req.message.strip():
        raise HTTPException(status_code=400, detail="Empty message.")
    try:
        return tutor.turn(req.session_id, req.message, provider_name=req.provider, focus=_focus(req))
    except (RuntimeError, ValueError) as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.post("/chat/stream")
def chat_stream(req: ChatRequest):
    if not req.message.strip():
        raise HTTPException(status_code=400, detail="Empty message.")

    def events():
        for event in tutor.turn_stream(req.session_id, req.message, provider_name=req.provider, focus=_focus(req)):
            yield f"event: {event['event']}\ndata: {json.dumps(event, ensure_ascii=False)}\n\n"

    return StreamingResponse(events(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


@app.get("/api/status")
def status():
    """The first provider in HSK_AGENT_PROVIDER's priority list that's reachable, and its model."""
    names = [n.strip() for n in os.environ.get("HSK_AGENT_PROVIDER", "").split(",") if n.strip()]
    first = None
    for name in names:
        model, reachable = _probe(name)
        first = first or (name, model)
        if reachable:
            return {"provider": name, "model": model, "tutor_available": True,
                    "fallbacks": names, "graph_loaded": retrieval.graph_exists()}
    name, model = first or (None, None)
    return {"provider": name, "model": model, "tutor_available": False,
            "fallbacks": names, "graph_loaded": retrieval.graph_exists()}


def _probe(name: str) -> tuple[str | None, bool]:
    """(model label, reachable) for one provider; local servers are pinged, the Anthropic API isn't."""
    import urllib.request
    if name == "llamacpp":
        url = os.environ.get("LLAMACPP_BASE_URL", "http://localhost:8080").rstrip("/")
        try:  # llama-server knows which GGUF it loaded; show that, not the URL
            with urllib.request.urlopen(url + "/v1/models", timeout=2) as r:
                model_id = json.loads(r.read())["data"][0]["id"]
            return Path(model_id.replace("\\", "/")).stem, True
        except Exception:
            return url, False
    if name == "ollama":
        model = os.environ.get("OLLAMA_MODEL", "gemma3n:e4b")
        url = os.environ.get("OLLAMA_BASE_URL", "http://localhost:11434").rstrip("/")
        try:
            with urllib.request.urlopen(url + "/api/tags", timeout=2) as r:
                return model, any(m["name"] == model for m in json.loads(r.read()).get("models", []))
        except Exception:
            return model, False
    if name == "openrouter":
        from agent.providers import OpenRouterProvider
        models = os.environ.get("OPENROUTER_MODEL", OpenRouterProvider.DEFAULT_MODELS)
        return models.split(",")[0].strip(), bool(os.environ.get("OPENROUTER_API_KEY"))
    if name == "anthropic":
        return os.environ.get("ANTHROPIC_MODEL", "claude-sonnet-5-5"), bool(os.environ.get("ANTHROPIC_API_KEY"))
    return None, False


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
