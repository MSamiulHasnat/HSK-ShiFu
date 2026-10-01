"""
HSK Knowledge Agent
RAG agent that uses Claude API + local HSK vector store.
Ensures all answers are grounded in HSK textbook data.
"""

import json
import logging
from typing import Dict, List, Optional
from anthropic import Anthropic

logger = logging.getLogger(__name__)


class HSKAgent:
    """HSK Knowledge Agent using Claude + RAG."""

    def __init__(self,
                 api_key: str,
                 vector_store,
                 model: str = "claude-3-5-sonnet-20241022",
                 temperature: float = 0.3,
                 max_tokens: int = 1000):
        """
        Initialize HSK Agent.

        Args:
            api_key: Anthropic API key
            vector_store: HSKVectorStore instance
            model: Claude model to use
            temperature: Lower = more factual
            max_tokens: Max response length
        """
        self.client = Anthropic()
        self.vector_store = vector_store
        self.model = model
        self.temperature = temperature
        self.max_tokens = max_tokens
        self.conversation_history = []

    def _retrieve_context(self, query: str, k: int = 5) -> List[Dict]:
        """Retrieve relevant HSK content from vector store."""
        results = self.vector_store.search(query, k=k)
        return results

    def _format_context(self, results: List[Dict]) -> str:
        """Format retrieved results as context for Claude."""
        if not results:
            return "No relevant HSK content found."

        context_parts = []

        for i, result in enumerate(results, 1):
            metadata = result["metadata"]
            content_type = metadata.get("type", "unknown")

            if content_type == "vocabulary":
                context_parts.append(
                    f"[Vocab {i}] {metadata['chinese']} ({metadata['pinyin']}) - {metadata['english']} "
                    f"[HSK {metadata['level']}]"
                )
            elif content_type == "grammar":
                context_parts.append(
                    f"[Grammar {i}] {metadata['rule_name']}: {metadata['explanation']} "
                    f"[HSK {metadata['level']}]"
                )
            elif content_type == "example":
                context_parts.append(
                    f"[Example {i}] {metadata['chinese']} - {metadata['english']} "
                    f"[HSK {metadata['level']}]"
                )

        return "\n".join(context_parts)

    def _create_system_prompt(self) -> str:
        """Create system prompt for Claude."""
        return """You are an HSK (Hanyu Shuiping Kaoshi) expert tutor. Your role is to help learners understand Chinese grammar, vocabulary, and language rules based on official HSK textbooks.

IMPORTANT RULES:
1. Only provide information found in the HSK textbooks
2. Always cite the HSK level and source material (vocabulary list, grammar section, example sentences)
3. If a question cannot be answered from HSK materials, say explicitly: "This information is not covered in the HSK textbooks I have access to."
4. Do not make up information or invent examples not from the textbooks
5. Be precise about which HSK level (1-6) each item belongs to
6. When explaining grammar, use examples from the textbooks
7. Maintain accuracy - if you're uncertain, admit it rather than guessing

Format your responses clearly with:
- The main answer based on HSK materials
- Citations (e.g., "HSK Level 1, Vocabulary" or "HSK Level 2, Grammar")
- Example sentences from the textbooks when relevant"""

    def answer(self, user_question: str, include_sources: bool = True) -> Dict:
        """
        Answer a question using RAG + Claude.

        Args:
            user_question: User's question
            include_sources: Include source citations

        Returns:
            Dictionary with answer and metadata
        """
        # Retrieve context
        logger.info(f"Retrieving context for: {user_question}")
        results = self._retrieve_context(user_question, k=5)
        context = self._format_context(results)

        # Add to conversation history
        self.conversation_history.append({
            "role": "user",
            "content": user_question
        })

        # Create messages for Claude
        system_prompt = self._create_system_prompt()

        # Build the user message with context
        augmented_question = f"""Based on the following HSK textbook materials:

{context}

---

Please answer this question: {user_question}

Remember to cite which HSK level and material type (vocabulary, grammar, or examples) you're referencing."""

        messages = self.conversation_history.copy()
        messages[-1]["content"] = augmented_question

        # Call Claude API
        logger.info("Calling Claude API...")
        response = self.client.messages.create(
            model=self.model,
            max_tokens=self.max_tokens,
            temperature=self.temperature,
            system=system_prompt,
            messages=messages
        )

        answer_text = response.content[0].text

        # Add assistant response to history
        self.conversation_history.append({
            "role": "assistant",
            "content": answer_text
        })

        # Prepare result
        result = {
            "answer": answer_text,
            "user_question": user_question,
            "model": self.model,
            "sources": results if include_sources else [],
            "source_summary": self._summarize_sources(results)
        }

        return result

    def _summarize_sources(self, results: List[Dict]) -> str:
        """Create a summary of retrieved sources."""
        if not results:
            return "No HSK materials found for this query."

        summary_lines = []
        for result in results:
            meta = result["metadata"]
            source_type = meta.get("type", "unknown").upper()
            level = meta.get("level", "?")
            summary_lines.append(f"• {source_type} from HSK Level {level}")

        return "\n".join(summary_lines)

    def clear_history(self):
        """Clear conversation history."""
        self.conversation_history = []
        logger.info("Cleared conversation history")

    def get_conversation_history(self) -> List[Dict]:
        """Get current conversation history."""
        return self.conversation_history

    def set_context_window(self, window_size: int):
        """Keep only recent messages in context."""
        if len(self.conversation_history) > window_size:
            self.conversation_history = self.conversation_history[-window_size:]


def main():
    """Example usage (requires ANTHROPIC_API_KEY env var)."""
    import os
    from vector_store import HSKVectorStore

    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        print("Error: ANTHROPIC_API_KEY not set")
        return

    # Initialize vector store
    vector_store = HSKVectorStore()

    # Initialize agent
    agent = HSKAgent(api_key, vector_store)

    # Example queries
    queries = [
        "What is the meaning of 我是学生?",
        "Explain the 把 grammar pattern",
        "How do I use 了 to indicate completed actions?"
    ]

    for query in queries:
        print(f"\nQ: {query}")
        result = agent.answer(query)
        print(f"A: {result['answer']}")
        print(f"Sources: {result['source_summary']}")


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    main()
