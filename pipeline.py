"""
HSK Agent Pipeline
Orchestrates the full pipeline: extract → parse → embed → query
"""

import os
import json
import logging
import sys
from pathlib import Path
from typing import Dict, Optional
from pdf_extractor import HSKPDFExtractor
from content_parser import HSKContentParser
from vector_store import HSKVectorStore
from hsk_agent import HSKAgent

logger = logging.getLogger(__name__)


class HSKAgentPipeline:
    """Full pipeline for HSK knowledge agent."""

    def __init__(self, config_path: str = "config.yaml"):
        """Initialize pipeline with config."""
        self.config_path = config_path
        self.config = self._load_config()

        self.extractor = None
        self.parser = None
        self.vector_store = None
        self.agent = None

    def _load_config(self) -> Dict:
        """Load configuration from YAML."""
        import yaml

        with open(self.config_path, 'r', encoding='utf-8') as f:
            return yaml.safe_load(f)

    def step_1_extract_pdfs(self) -> Dict:
        """Step 1: Extract text from HSK PDFs."""
        logger.info("=" * 60)
        logger.info("STEP 1: Extracting HSK PDFs")
        logger.info("=" * 60)

        pdf_config = self.config.get("pdf", {})
        self.extractor = HSKPDFExtractor(
            pdf_dir=pdf_config.get("input_dir", "HSK-Textbooks"),
            output_dir="hsk_data"
        )

        levels = pdf_config.get("levels", [1, 2, 3])
        results = self.extractor.extract_all_levels(levels)

        # Save results
        self.extractor.save_extracted_data(results, format="json")
        self.extractor.save_extracted_data(results, format="txt")

        logger.info("✓ Step 1 complete: PDFs extracted")
        return results

    def step_2_parse_content(self) -> Dict:
        """Step 2: Parse extracted content into structured format."""
        logger.info("=" * 60)
        logger.info("STEP 2: Parsing HSK Content")
        logger.info("=" * 60)

        self.parser = HSKContentParser(output_dir="hsk_data")

        # Parse extracted JSON
        extracted_file = "hsk_data/hsk_extracted_data.json"
        if not Path(extracted_file).exists():
            logger.error(f"Extracted data not found at {extracted_file}")
            return {"error": "Run step 1 first"}

        results = self.parser.parse_extracted_json(extracted_file)

        # Save parsed data
        self.parser.save_parsed_data()

        logger.info("✓ Step 2 complete: Content parsed")
        logger.info(f"  Vocabulary: {len(self.parser.vocabulary)} entries")
        logger.info(f"  Grammar: {len(self.parser.grammar_rules)} rules")
        logger.info(f"  Examples: {len(self.parser.example_sentences)} sentences")

        return results

    def step_3_build_vector_store(self) -> Dict:
        """Step 3: Build vector embeddings."""
        logger.info("=" * 60)
        logger.info("STEP 3: Building Vector Store")
        logger.info("=" * 60)

        embedding_config = self.config.get("embeddings", {})
        self.vector_store = HSKVectorStore(
            model_name=embedding_config.get("model", "sentence-transformers/distilbert-base-multilingual-cased"),
            store_path=self.config.get("vectorstore", {}).get("store_path", "hsk_data/faiss_index"),
            embedding_dim=embedding_config.get("embedding_dim", 384)
        )

        # Add content
        vocab_file = "hsk_data/vocabulary.json"
        grammar_file = "hsk_data/grammar_rules.json"
        examples_file = "hsk_data/example_sentences.json"

        if Path(vocab_file).exists():
            self.vector_store.add_vocabulary(vocab_file)
        if Path(grammar_file).exists():
            self.vector_store.add_grammar_rules(grammar_file)
        if Path(examples_file).exists():
            self.vector_store.add_example_sentences(examples_file)

        # Save
        self.vector_store.save()

        stats = self.vector_store.get_statistics()
        logger.info("✓ Step 3 complete: Vector store built")
        logger.info(f"  Total vectors: {stats['total_vectors']}")
        logger.info(f"  By type: {stats['by_type']}")
        logger.info(f"  By level: {stats['by_level']}")

        return stats

    def step_4_initialize_agent(self) -> bool:
        """Step 4: Initialize Claude RAG agent."""
        logger.info("=" * 60)
        logger.info("STEP 4: Initializing Claude Agent")
        logger.info("=" * 60)

        if not self.vector_store:
            logger.error("Vector store not initialized. Run step 3 first.")
            return False

        api_key = os.environ.get("ANTHROPIC_API_KEY")
        if not api_key:
            logger.error("ANTHROPIC_API_KEY environment variable not set")
            return False

        claude_config = self.config.get("claude", {})
        self.agent = HSKAgent(
            api_key=api_key,
            vector_store=self.vector_store,
            model=claude_config.get("model", "claude-3-5-sonnet-20241022"),
            temperature=claude_config.get("temperature", 0.3),
            max_tokens=claude_config.get("max_tokens", 1000)
        )

        logger.info("✓ Step 4 complete: Claude agent ready")
        return True

    def step_5_build_knowledge_graph(self) -> Dict:
        """Step 5: Build knowledge graph (graphify integration)."""
        logger.info("=" * 60)
        logger.info("STEP 5: Building Knowledge Graph")
        logger.info("=" * 60)

        # This step is a placeholder for graphify integration
        # In production, this would call graphify to analyze relationships

        graph_config = self.config.get("graph", {})
        if not graph_config.get("enabled", True):
            logger.info("Knowledge graph disabled in config")
            return {"status": "skipped"}

        logger.info("Knowledge graph integration placeholder")
        logger.info("(Ready to integrate with graphify CLI)")

        return {
            "status": "ready_for_graphify",
            "graph_output_path": graph_config.get("output_path", "hsk_data/knowledge_graph.json"),
            "relationship_types": graph_config.get("relationship_types", [])
        }

    def run_full_pipeline(self) -> Dict:
        """Run the complete pipeline."""
        logger.info("\n\n" + "=" * 60)
        logger.info("HSK KNOWLEDGE AGENT - FULL PIPELINE")
        logger.info("=" * 60 + "\n")

        try:
            # Step 1: Extract
            step1 = self.step_1_extract_pdfs()
            if any("error" in str(v) for v in step1.values()):
                logger.warning("Step 1: Extraction had errors, but continuing...")

            # Step 2: Parse
            step2 = self.step_2_parse_content()

            # Step 3: Vector store
            step3 = self.step_3_build_vector_store()

            # Step 4: Agent
            agent_ready = self.step_4_initialize_agent()

            # Step 5: Knowledge graph
            step5 = self.step_5_build_knowledge_graph()

            logger.info("\n" + "=" * 60)
            logger.info("✓ PIPELINE COMPLETE")
            logger.info("=" * 60)

            return {
                "status": "success",
                "step1_extract": "complete",
                "step2_parse": step2,
                "step3_vector_store": step3,
                "step4_agent": "ready" if agent_ready else "failed",
                "step5_knowledge_graph": step5
            }

        except Exception as e:
            logger.error(f"Pipeline failed: {e}", exc_info=True)
            return {"status": "failed", "error": str(e)}

    def query(self, question: str) -> Dict:
        """Query the agent."""
        if not self.agent:
            logger.error("Agent not initialized. Run pipeline first.")
            return {"error": "Agent not ready"}

        return self.agent.answer(question, include_sources=True)


def main():
    """Main entry point."""
    import argparse

    parser = argparse.ArgumentParser(description="HSK Knowledge Agent Pipeline")
    parser.add_argument("--step", type=int, choices=[1, 2, 3, 4, 5, 0],
                       default=0, help="Run specific step (0=all)")
    parser.add_argument("--query", type=str, help="Query the agent after pipeline")
    parser.add_argument("--config", type=str, default="config.yaml", help="Config file")

    args = parser.parse_args()

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
        handlers=[
            logging.FileHandler("hsk_agent.log"),
            logging.StreamHandler()
        ]
    )

    pipeline = HSKAgentPipeline(config_path=args.config)

    # Run pipeline
    if args.step == 0:
        # Full pipeline
        results = pipeline.run_full_pipeline()
    elif args.step == 1:
        results = {"step1": pipeline.step_1_extract_pdfs()}
    elif args.step == 2:
        results = {"step2": pipeline.step_2_parse_content()}
    elif args.step == 3:
        results = {"step3": pipeline.step_3_build_vector_store()}
    elif args.step == 4:
        results = {"step4": pipeline.step_4_initialize_agent()}
    elif args.step == 5:
        results = {"step5": pipeline.step_5_build_knowledge_graph()}

    print("\nResults:", json.dumps(results, indent=2, ensure_ascii=False))

    # Query if specified
    if args.query and pipeline.agent:
        print("\n" + "=" * 60)
        print("QUERY TEST")
        print("=" * 60)
        query_result = pipeline.query(args.query)
        print(f"\nQ: {args.query}")
        print(f"\nA: {query_result['answer']}")
        print(f"\nSources: {query_result['source_summary']}")


if __name__ == "__main__":
    main()
