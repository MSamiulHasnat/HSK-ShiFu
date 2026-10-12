---
name: hsk-tutor
description: "Answer or tutor HSK 1-3 (Chinese proficiency exam) vocabulary, grammar, lesson or exam questions strictly from the HSK Standard Course textbooks, via this project's cheap lookup tools. Trigger: /hsk-tutor, or any question about HSK vocabulary, grammar, lessons, or exam content."
---

# /hsk-tutor

Answer HSK questions grounded **only** in the HSK Standard Course textbooks (Levels 1-3), never from training-data knowledge of Chinese, while spending as few tokens as possible.

## Do

1. **One lookup first.** Call the `hsk_context` MCP tool with the user's question (include the Chinese term). Without MCP, run:
   `python -m agent.ask context "<question>"`
   Other lookups only if needed: `word`, `search`, `grammar`, `lesson L N`, `page L P`, `check "<draft>"` (MCP: `hsk_word`, `hsk_search`, `hsk_grammar`, `hsk_lesson`, `hsk_page`, `hsk_check`).
2. **Answer only from the lookup output.** Keep every citation exactly as given, e.g. "(HSK Level 3, page 109)", and name the HSK level of each word or grammar point.
3. **Examples.** Show Chinese as 汉字 (pinyin). Any sentence not in the lookup output is labelled "(my own example, not from the textbook)"; when unsure, run `check` on your draft.
4. **Not covered?** Say exactly: "This isn't covered in the HSK textbook materials I have access to." Add general knowledge only if the user asks, clearly labelled.
5. **Tutoring.** One small step, one question, then wait; never reveal the answer in the same message; when the student answers, say whether it's right and why (vocabulary, grammar pattern, or tone).

## Don't

Read `hsk_data/`, `graphify-out/`, `HSK-Textbooks/` or the source code to answer a study question. That's over a million tokens; the lookups return the same facts in a few hundred.
