"""
Vector Store for HSK Knowledge
Uses FAISS for local embeddings and semantic search without external APIs.
"""

import json
import logging
import numpy as np
from pathlib import Path
from typing import Dict, List, Tuple, Optional
import faiss
from sentence_transformers import SentenceTransformer

logger = logging.getLogger(__name__)


class HSKVectorStore:
    """Local vector store for HSK content using FAISS."""

    def __init__(self,
                 model_name: str = "sentence-transformers/distilbert-base-multilingual-cased",
                 store_path: str = "hsk_data/faiss_index",
                 embedding_dim: int = 384):
        """
        Initialize vector store.

        Args:
            model_name: Sentence transformer model for embeddings
            store_path: Path to save/load FAISS index
            embedding_dim: Dimension of embeddings
        """
        self.store_path = Path(store_path)
        self.store_path.mkdir(parents=True, exist_ok=True)

        logger.info(f"Loading embedding model: {model_name}")
        self.model = SentenceTransformer(model_name)
        self.embedding_dim = embedding_dim

        # FAISS index
        self.index = None
        self.metadata = []  # Store metadata for each embedding

        self._load_or_create_index()

    def _load_or_create_index(self):
        """Load existing FAISS index or create new one."""
        index_file = self.store_path / "faiss.index"
        metadata_file = self.store_path / "metadata.json"

        if index_file.exists() and metadata_file.exists():
            logger.info("Loading existing FAISS index...")
            self.index = faiss.read_index(str(index_file))
            with open(metadata_file, 'r', encoding='utf-8') as f:
                self.metadata = json.load(f)
            logger.info(f"Loaded {len(self.metadata)} vectors")
        else:
            logger.info("Creating new FAISS index...")
            self.index = faiss.IndexFlatL2(self.embedding_dim)

    def add_vocabulary(self, vocab_file: str):
        """Add vocabulary entries to vector store."""
        with open(vocab_file, 'r', encoding='utf-8') as f:
            vocab_list = json.load(f)

        texts = []
        metadata = []

        for vocab in vocab_list:
            # Create searchable text: Chinese + pinyin + English + part of speech
            text = f"{vocab['chinese']} {vocab['pinyin']} {vocab['english']}"
            if vocab.get('pos'):
                text += f" {vocab['pos']}"

            texts.append(text)
            metadata.append({
                "type": "vocabulary",
                "chinese": vocab["chinese"],
                "pinyin": vocab["pinyin"],
                "english": vocab["english"],
                "level": vocab["level"],
                "lesson": vocab.get("lesson")
            })

        self._add_texts(texts, metadata)
        logger.info(f"Added {len(vocab_list)} vocabulary entries")

    def add_grammar_rules(self, grammar_file: str):
        """Add grammar rules to vector store."""
        with open(grammar_file, 'r', encoding='utf-8') as f:
            grammar_list = json.load(f)

        texts = []
        metadata = []

        for grammar in grammar_list:
            # Create searchable text: rule name + explanation + examples
            text = f"{grammar['rule_name']} {grammar['explanation']}"
            if grammar.get('example_sentences'):
                text += " " + " ".join(grammar['example_sentences'][:2])

            texts.append(text)
            metadata.append({
                "type": "grammar",
                "rule_name": grammar["rule_name"],
                "level": grammar["level"],
                "lesson": grammar.get("lesson"),
                "explanation": grammar["explanation"][:100]  # Truncate for metadata
            })

        self._add_texts(texts, metadata)
        logger.info(f"Added {len(grammar_list)} grammar rules")

    def add_example_sentences(self, examples_file: str):
        """Add example sentences to vector store."""
        with open(examples_file, 'r', encoding='utf-8') as f:
            examples_list = json.load(f)

        texts = []
        metadata = []

        for example in examples_list:
            text = f"{example['chinese']} {example['english']}"
            if example.get('pinyin'):
                text += f" {example['pinyin']}"

            texts.append(text)
            metadata.append({
                "type": "example",
                "chinese": example["chinese"],
                "english": example["english"],
                "level": example["level"]
            })

        self._add_texts(texts, metadata)
        logger.info(f"Added {len(examples_list)} example sentences")

    def _add_texts(self, texts: List[str], metadata: List[Dict]):
        """Add texts with metadata to FAISS index."""
        if not texts:
            return

        # Encode texts
        logger.info(f"Encoding {len(texts)} texts...")
        embeddings = self.model.encode(texts, show_progress_bar=True)
        embeddings = np.array(embeddings, dtype=np.float32)

        # Add to FAISS index
        self.index.add(embeddings)
        self.metadata.extend(metadata)

        logger.info(f"Vector store now contains {len(self.metadata)} vectors")

    def search(self, query: str, k: int = 5, level: Optional[int] = None) -> List[Dict]:
        """
        Search the vector store.

        Args:
            query: Search query
            k: Number of results
            level: Optional HSK level filter

        Returns:
            List of results with metadata and similarity
        """
        # Encode query
        query_embedding = self.model.encode([query])[0]
        query_embedding = np.array([query_embedding], dtype=np.float32)

        # Search
        distances, indices = self.index.search(query_embedding, k * 2)  # Get extra results for filtering

        results = []
        for idx, distance in zip(indices[0], distances[0]):
            if idx < len(self.metadata):
                metadata = self.metadata[int(idx)]

                # Filter by level if specified
                if level and metadata.get("level") != level:
                    continue

                results.append({
                    "metadata": metadata,
                    "similarity": 1 - (distance / 100),  # Normalize similarity
                    "index": int(idx)
                })

                if len(results) >= k:
                    break

        return results

    def search_by_level(self, query: str, level: int, k: int = 5) -> List[Dict]:
        """Search within a specific HSK level."""
        return self.search(query, k, level=level)

    def search_by_type(self, query: str, content_type: str, k: int = 5) -> List[Dict]:
        """Search by content type (vocabulary, grammar, example)."""
        results = self.search(query, k * 2)
        return [r for r in results if r["metadata"].get("type") == content_type][:k]

    def save(self):
        """Save FAISS index and metadata to disk."""
        index_file = self.store_path / "faiss.index"
        metadata_file = self.store_path / "metadata.json"

        faiss.write_index(self.index, str(index_file))
        with open(metadata_file, 'w', encoding='utf-8') as f:
            json.dump(self.metadata, f, ensure_ascii=False, indent=2)

        logger.info(f"Saved index to {self.store_path}")

    def get_statistics(self) -> Dict:
        """Get vector store statistics."""
        type_counts = {}
        level_counts = {}

        for meta in self.metadata:
            content_type = meta.get("type", "unknown")
            level = meta.get("level", "unknown")

            type_counts[content_type] = type_counts.get(content_type, 0) + 1
            level_counts[str(level)] = level_counts.get(str(level), 0) + 1

        return {
            "total_vectors": len(self.metadata),
            "by_type": type_counts,
            "by_level": level_counts
        }


def main():
    """Example usage."""
    vector_store = HSKVectorStore()

    # Add content
    vector_store.add_vocabulary("hsk_data/vocabulary.json")
    vector_store.add_grammar_rules("hsk_data/grammar_rules.json")
    vector_store.add_example_sentences("hsk_data/example_sentences.json")

    # Save
    vector_store.save()

    # Test search
    results = vector_store.search("我是学生", k=3)
    for result in results:
        print(f"✓ {result['metadata']} (similarity: {result['similarity']:.2f})")

    # Stats
    print("Vector store stats:", vector_store.get_statistics())


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    main()
