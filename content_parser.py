"""
HSK Content Parser
Parses extracted HSK text into structured vocabulary, grammar, and examples.
"""

import json
import logging
import re
from pathlib import Path
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass, asdict

logger = logging.getLogger(__name__)


@dataclass
class Vocabulary:
    """Vocabulary entry from HSK textbook."""
    chinese: str
    pinyin: str
    english: str
    level: int
    lesson: Optional[int] = None
    pos: Optional[str] = None  # Part of speech
    example_sentence: Optional[str] = None
    strokes: Optional[int] = None
    radical: Optional[str] = None


@dataclass
class GrammarRule:
    """Grammar rule from HSK textbook."""
    rule_name: str
    level: int
    lesson: Optional[int]
    explanation: str
    example_sentences: List[str]
    pattern: Optional[str] = None
    usage_notes: Optional[str] = None


@dataclass
class ExampleSentence:
    """Example sentence with translation."""
    chinese: str
    pinyin: Optional[str]
    english: str
    level: int
    grammar_points: List[str]


class HSKContentParser:
    """Parse extracted HSK content into structured data."""

    def __init__(self, output_dir: str = "hsk_data"):
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(exist_ok=True)

        self.vocabulary: List[Vocabulary] = []
        self.grammar_rules: List[GrammarRule] = []
        self.example_sentences: List[ExampleSentence] = []

    def parse_extracted_json(self, json_file: str) -> Dict:
        """
        Parse the extracted JSON data from HSKPDFExtractor.

        Args:
            json_file: Path to extracted JSON file

        Returns:
            Dictionary with parsed content
        """
        with open(json_file, 'r', encoding='utf-8') as f:
            data = json.load(f)

        parsed_results = {}

        for level_key, level_data in data.items():
            if "error" in level_data:
                continue

            level = level_data.get("level", 1)
            text = level_data.get("text", "")

            logger.info(f"Parsing {level_key}...")

            # Parse vocabulary, grammar, examples from raw text
            vocab = self._extract_vocabulary(text, level)
            grammar = self._extract_grammar_rules(text, level)
            examples = self._extract_example_sentences(text, level)

            self.vocabulary.extend(vocab)
            self.grammar_rules.extend(grammar)
            self.example_sentences.extend(examples)

            parsed_results[level_key] = {
                "vocabulary_count": len(vocab),
                "grammar_rules_count": len(grammar),
                "example_sentences_count": len(examples)
            }

        return parsed_results

    def _extract_vocabulary(self, text: str, level: int) -> List[Vocabulary]:
        """Extract vocabulary entries from text."""
        vocab_list = []

        # Simple heuristic: look for Chinese characters followed by pinyin and English
        # This can be enhanced with ML/NLP
        lines = text.split('\n')

        for i, line in enumerate(lines):
            line = line.strip()

            # Skip empty lines and page markers
            if not line or '---' in line or 'Page' in line:
                continue

            # Look for vocabulary table entries (Chinese | Pinyin | English | ...)
            if '|' in line:
                parts = [p.strip() for p in line.split('|')]
                if len(parts) >= 3:
                    chinese = parts[0]
                    pinyin = parts[1]
                    english = parts[2]

                    # Basic validation
                    if self._is_chinese(chinese) and len(pinyin) > 0:
                        vocab = Vocabulary(
                            chinese=chinese,
                            pinyin=pinyin,
                            english=english,
                            level=level,
                            lesson=self._extract_lesson_number(line)
                        )
                        vocab_list.append(vocab)

        return vocab_list

    def _extract_grammar_rules(self, text: str, level: int) -> List[GrammarRule]:
        """Extract grammar rules from text."""
        grammar_list = []

        lines = text.split('\n')
        i = 0

        while i < len(lines):
            line = lines[i].strip()

            # Look for grammar section markers
            if any(marker in line for marker in ['Grammar', '语法', 'Pattern', '句式']):
                # Try to extract rule name and explanation
                rule_name = line
                explanation_lines = []
                examples = []

                i += 1
                while i < len(lines) and not any(marker in lines[i] for marker in ['---', 'Lesson', '课程']):
                    next_line = lines[i].strip()

                    if next_line.startswith('Example') or '例' in next_line:
                        examples.append(next_line)
                    elif next_line and not next_line.startswith('['):
                        explanation_lines.append(next_line)

                    i += 1

                if explanation_lines:
                    grammar = GrammarRule(
                        rule_name=rule_name,
                        level=level,
                        lesson=self._extract_lesson_number('\n'.join(lines[max(0, i-10):i])),
                        explanation=' '.join(explanation_lines[:3]),  # First 3 lines
                        example_sentences=examples[:5]  # First 5 examples
                    )
                    grammar_list.append(grammar)
            else:
                i += 1

        return grammar_list

    def _extract_example_sentences(self, text: str, level: int) -> List[ExampleSentence]:
        """Extract example sentences from text."""
        examples = []

        lines = text.split('\n')

        for line in lines:
            line = line.strip()

            # Look for lines with Chinese text and English translation
            if self._is_chinese(line) and '|' in line:
                parts = [p.strip() for p in line.split('|')]
                if len(parts) >= 2:
                    chinese = parts[0]
                    english = parts[1] if len(parts) > 1 else ""

                    example = ExampleSentence(
                        chinese=chinese,
                        pinyin=self._extract_pinyin(line) if len(parts) > 2 else None,
                        english=english,
                        level=level,
                        grammar_points=[]
                    )
                    examples.append(example)

        return examples

    def _is_chinese(self, text: str) -> bool:
        """Check if text contains Chinese characters."""
        return any('一' <= ch <= '鿿' for ch in text)

    def _extract_lesson_number(self, text: str) -> Optional[int]:
        """Extract lesson number from text."""
        match = re.search(r'[Ll]esson\s+(\d+)|第\s*(\d+)\s*课', text)
        if match:
            return int(match.group(1) or match.group(2))
        return None

    def _extract_pinyin(self, text: str) -> Optional[str]:
        """Extract pinyin from text (basic heuristic)."""
        # Look for syllables with tone marks or numbers
        match = re.search(r'([a-z]+[1-4])', text.lower())
        if match:
            return match.group(1)
        return None

    def save_parsed_data(self):
        """Save parsed content to JSON files."""
        # Save vocabulary
        vocab_file = self.output_dir / "vocabulary.json"
        with open(vocab_file, 'w', encoding='utf-8') as f:
            json.dump([asdict(v) for v in self.vocabulary], f, ensure_ascii=False, indent=2)
        logger.info(f"Saved {len(self.vocabulary)} vocabulary entries to {vocab_file}")

        # Save grammar rules
        grammar_file = self.output_dir / "grammar_rules.json"
        with open(grammar_file, 'w', encoding='utf-8') as f:
            json.dump([asdict(g) for g in self.grammar_rules], f, ensure_ascii=False, indent=2)
        logger.info(f"Saved {len(self.grammar_rules)} grammar rules to {grammar_file}")

        # Save example sentences
        examples_file = self.output_dir / "example_sentences.json"
        with open(examples_file, 'w', encoding='utf-8') as f:
            json.dump([asdict(e) for e in self.example_sentences], f, ensure_ascii=False, indent=2)
        logger.info(f"Saved {len(self.example_sentences)} example sentences to {examples_file}")

    def get_vocabulary_by_level(self, level: int) -> List[Vocabulary]:
        """Get all vocabulary for a specific HSK level."""
        return [v for v in self.vocabulary if v.level == level]

    def get_grammar_by_level(self, level: int) -> List[GrammarRule]:
        """Get all grammar rules for a specific HSK level."""
        return [g for g in self.grammar_rules if g.level == level]


def main():
    """Example usage."""
    parser = HSKContentParser()

    # Parse extracted data
    results = parser.parse_extracted_json("hsk_data/hsk_extracted_data.json")
    print("✓ Parsing results:", results)

    # Save structured data
    parser.save_parsed_data()
    print("✓ Parsed data saved!")


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    main()
