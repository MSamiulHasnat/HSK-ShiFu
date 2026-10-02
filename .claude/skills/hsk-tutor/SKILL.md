---
name: hsk-tutor
description: "Answer HSK (Chinese proficiency exam) vocabulary/grammar/exam questions strictly from this project's graphify knowledge graph (graphify-out/graph.json), built from the official HSK Standard Course textbooks. Trigger: /hsk-tutor, or any question about HSK vocabulary, grammar, lessons, or exam content."
---

# /hsk-tutor

Answers HSK questions grounded **only** in `graphify-out/graph.json` -- never from training-data knowledge of Chinese. This is the project's core guarantee: every fact traces back to a specific page of an official HSK textbook.

## What you must do when invoked

1. **Check the graph exists.** If `graphify-out/graph.json` is missing, tell the user to run the graphify build first (see `INGESTION_REPORT.md`) and stop.

2. **Expand the query against the graph's vocabulary.** Follow Step 0 in `.claude/skills/graphify/references/query.md`: extract the graph's label vocabulary, pick up to 12 matching tokens for the user's question (never invent tokens), print the expansion so it's auditable.

3. **Retrieve.**
   - General "what/how" questions: `graphify query "<expanded question>"`
   - "How does X relate to Y": `graphify path "X" "Y"`
   - "Explain X": `graphify explain "X"`

4. **Synthesize strictly from the result.**
   - Every claim must trace to a `NODE` label or an edge's `relation`.
   - Cite the source for every fact: turn `src=levelN/page_NNN.md` into "(HSK Level N, page NNN)", adding the lesson name from the node's `community` field when relevant.
   - If an edge is `[INFERRED]`, say the graph infers this rather than stating it as directly sourced. If `[AMBIGUOUS]`, flag it as uncertain.
   - If the query returns no matching nodes, or nothing in the result actually answers the question, say plainly: **"This isn't covered in the HSK textbook materials I have access to."** Do not fill the gap with general Chinese-language knowledge unless the user explicitly asks for that as a separate, clearly-labeled addition.

5. **HSK level awareness.** Always note which HSK level (1/2/3) a vocabulary word or grammar point belongs to -- this is pedagogically load-bearing for the learner.

6. **Close the feedback loop (optional but encouraged).** After answering, save the result so future queries benefit:
   ```bash
   graphify save-result --question "<original question>" --answer "<your answer>" --type query --nodes <cited node labels>
   ```

## Example

> User: "What does 把字句 mean and when do I use it?"

1. Query expansion: tokens `[把字句, ba, sentence]` (from graph vocab).
2. `graphify query "把字句"` → returns `Grammar: 把字句1 A把B+V+…` and `把字句2 A把B+V+在/到/给…` nodes, sourced to `level3/page_109.md` and `level3/page_117.md`, both in the "Don't Forget to Turn Off the Air Conditioner" (Lesson 11) community.
3. Answer: explain both patterns using only what the NODE labels/edges say, citing "(HSK Level 3, Lesson 11, page 109)" and "(HSK Level 3, Lesson 11, page 117)".

## Also available

- Standalone CLI/API (no coding agent, optionally with your own LLM key): `agent/` — see `agent/README.md`.
- Same grounding rules apply in Codex (`AGENTS.md`) and Antigravity/Gemini CLI (`GEMINI.md`) for this project.
