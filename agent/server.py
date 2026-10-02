"""
Local web server for the HSK knowledge agent.

Run:
    python -m agent.server
    # or: uvicorn agent.server:app --reload --port 8000

Endpoints:
    GET  /           a minimal browser UI to ask questions (this is what "it's not
                      working" usually means -- there was no page here before)
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

from agent import prompts, retrieval, teacher
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


INDEX_HTML = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>HSK Knowledge Agent</title>
<style>
  :root { color-scheme: light dark; }
  body { font-family: -apple-system, Segoe UI, Roboto, sans-serif; max-width: 760px; margin: 2rem auto; padding: 0 1rem; line-height: 1.5; }
  h1 { font-size: 1.4rem; }
  textarea { width: 100%; box-sizing: border-box; font-size: 1rem; padding: 0.6rem; border-radius: 6px; border: 1px solid #8884; }
  button { margin-top: 0.6rem; padding: 0.5rem 1.2rem; font-size: 1rem; border-radius: 6px; border: 1px solid #8884; cursor: pointer; }
  button:disabled { opacity: 0.5; cursor: default; }
  .row { display: flex; gap: 0.6rem; align-items: center; flex-wrap: wrap; margin-top: 0.4rem; }
  .answer { margin-top: 1.2rem; padding: 1rem; border-radius: 8px; border: 1px solid #8884; white-space: pre-wrap; }
  .sources { margin-top: 0.6rem; font-size: 0.9rem; opacity: 0.8; }
  .meta { margin-top: 0.4rem; font-size: 0.85rem; opacity: 0.6; }
  details { margin-top: 0.8rem; }
  code { font-size: 0.85em; }
</style>
</head>
<body>
<h1>HSK Knowledge Agent</h1>
<p>Answers are pulled strictly from the HSK knowledge graph (<code>graphify-out/graph.json</code>) -- see <a href="/docs">/docs</a> for the raw API.</p>
<textarea id="q" rows="3" placeholder="e.g. Teach me 把字句"></textarea>
<div class="row">
  <button id="ask">Ask</button>
  <label><input type="radio" name="mode" value="teach" checked> 🧑‍🏫 Teach me (lesson + practice)</label>
  <label><input type="radio" name="mode" value="answer"> Quick answer</label>
</div>
<p class="meta">Ctrl+Enter to send. Lessons from a local model can take a minute or two.</p>
<div id="out"></div>
<script>
function renderMd(s) {
  return s.replace(/&/g, '&amp;').replace(/</g, '&lt;')
    .replace(/^#{1,4} (.*)$/gm, '<strong>$1</strong>')
    .replace(/\\*\\*(.+?)\\*\\*/g, '<strong>$1</strong>')
    .replace(/(^|[^*])\\*([^*\\n]+)\\*/g, '$1<em>$2</em>');
}
const out = document.getElementById('out');
const btn = document.getElementById('ask');
async function ask() {
  const question = document.getElementById('q').value.trim();
  if (!question) return;
  btn.disabled = true;
  out.innerHTML = '<p class="meta">Thinking&hellip;</p>';
  try {
    const resp = await fetch('/ask', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({question, mode: document.querySelector('input[name=mode]:checked').value})
    });
    const data = await resp.json();
    if (!resp.ok) {
      out.innerHTML = '<p class="answer">Error: ' + (data.detail || resp.statusText) + '</p>';
      return;
    }
    const sources = (data.sources || []).map(s => '<li>' + s + '</li>').join('');
    out.innerHTML =
      '<div class="answer">' + renderMd(data.answer) + '</div>' +
      (sources ? '<div class="sources"><strong>Sources</strong><ul>' + sources + '</ul></div>' : '') +
      '<div class="meta">provider: ' + (data.provider_used || '(none configured -- raw graph context shown)') + '</div>' +
      '<details><summary>Raw graph context</summary><pre>' + data.raw_context.replace(/</g, '&lt;') + '</pre></details>';
  } catch (e) {
    out.innerHTML = '<p class="answer">Request failed: ' + e + '</p>';
  } finally {
    btn.disabled = false;
  }
}
btn.addEventListener('click', ask);
document.getElementById('q').addEventListener('keydown', e => {
  if (e.key === 'Enter' && (e.ctrlKey || e.metaKey)) ask();
});
</script>
</body>
</html>"""


@app.get("/", response_class=HTMLResponse)
def index():
    return INDEX_HTML


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
