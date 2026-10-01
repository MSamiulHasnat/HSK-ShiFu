"""
Interactive HSK Agent Chat
Multi-turn conversation with verified HSK knowledge.
"""

import os
import logging
from pathlib import Path
from pipeline import HSKAgentPipeline

logging.basicConfig(level=logging.INFO, format="%(message)s")


def print_header():
    """Print welcome header."""
    print("\n" + "=" * 60)
    print("HSK KNOWLEDGE AGENT - Interactive Chat")
    print("=" * 60)
    print("\nWelcome! I can answer questions about:")
    print("  • HSK Vocabulary (all levels 1-3)")
    print("  • HSK Grammar rules and patterns")
    print("  • Example sentences from textbooks")
    print("  • Character radicals and stroke order")
    print("\nType 'exit' or 'quit' to end conversation")
    print("Type 'clear' to reset conversation history")
    print("Type 'stats' to see knowledge base statistics")
    print("=" * 60 + "\n")


def print_answer(result):
    """Pretty print answer with sources."""
    print("\n" + "-" * 60)
    print(result['answer'])
    print("-" * 60)

    if result['sources']:
        print("\n📚 Sources:")
        print(result['source_summary'])

    print()


def main():
    """Main chat loop."""
    print_header()

    # Initialize pipeline
    print("Loading HSK knowledge base...")
    pipeline = HSKAgentPipeline(config_path="config.yaml")

    # Check if pipeline is already built
    if not Path("hsk_data/faiss_index/faiss.index").exists():
        print("Knowledge base not found. Running pipeline...")
        print("(This may take 30-40 minutes on first run)\n")

        response = input("Continue? (y/n): ").strip().lower()
        if response != 'y':
            print("Cancelled.")
            return

        results = pipeline.run_full_pipeline()
        if results.get("status") != "success":
            print("Pipeline failed. Check logs.")
            return

    # Load components
    try:
        from vector_store import HSKVectorStore
        from hsk_agent import HSKAgent

        vector_store = HSKVectorStore()
        api_key = os.environ.get("ANTHROPIC_API_KEY")

        if not api_key:
            print("Error: ANTHROPIC_API_KEY not set")
            return

        agent = HSKAgent(api_key, vector_store)

        print("✓ HSK Agent ready!\n")
        print("Stats:", vector_store.get_statistics(), "\n")

    except Exception as e:
        print(f"Error loading components: {e}")
        return

    # Chat loop
    while True:
        try:
            user_input = input("You: ").strip()

            if not user_input:
                continue

            if user_input.lower() in ['exit', 'quit', 'bye']:
                print("\n再见! (Goodbye!)")
                break

            if user_input.lower() == 'clear':
                agent.clear_history()
                print("✓ Conversation history cleared\n")
                continue

            if user_input.lower() == 'stats':
                stats = vector_store.get_statistics()
                print(f"\nKnowledge Base Statistics:")
                print(f"  Total vectors: {stats['total_vectors']}")
                print(f"  By type: {stats['by_type']}")
                print(f"  By level: {stats['by_level']}\n")
                continue

            # Get answer
            print("\nAgent: ", end="", flush=True)
            result = agent.answer(user_input, include_sources=True)
            print_answer(result)

        except KeyboardInterrupt:
            print("\n\n再见! (Goodbye!)")
            break
        except Exception as e:
            print(f"\nError: {e}")
            print("Please try again.\n")


if __name__ == "__main__":
    main()
