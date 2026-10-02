"""
Local web server for the HSK knowledge agent.

Run:
    python -m agent.server
    # or: uvicorn agent.server:app --reload --port 8000

Endpoints:
    POST /ask        {"question": "...", "dfs": false, "budget": 2000, "provider": null}
                      -> {"question", "found", "answer", "sources", "provider_used", "raw_context"}
    GET  /graph/info  basic stats about the loaded graph (node/edge/community counts)
    GET  /healthz     liveness check
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

from agent import prompts, retrieval
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


class AskResponse(BaseModel):
    question: str
    found: bool
    answer: str
    sources: list[str]
    provider_used: Optional[str]
    raw_context: str


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
