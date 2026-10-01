"""
HSK PDF Extractor
Extracts text and metadata from HSK textbook PDFs while preserving structure.
"""

import os
import json
import logging
from pathlib import Path
from typing import Dict, List, Tuple, Optional
import pypdf
import pdfplumber

logger = logging.getLogger(__name__)


class HSKPDFExtractor:
    """Extract structured content from HSK textbook PDFs."""

    def __init__(self, pdf_dir: str, output_dir: str = "hsk_data"):
        """
        Initialize the PDF extractor.

        Args:
            pdf_dir: Directory containing HSK PDF files
            output_dir: Directory to save extracted content
        """
        self.pdf_dir = Path(pdf_dir)
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(exist_ok=True)

        # Create subdirectories
        self.text_dir = self.output_dir / "extracted_text"
        self.text_dir.mkdir(exist_ok=True)

    def extract_all_levels(self, levels: List[int] = [1, 2, 3]) -> Dict:
        """
        Extract all HSK level PDFs.

        Args:
            levels: List of HSK levels to extract

        Returns:
            Dictionary with extraction results for each level
        """
        results = {}

        for level in levels:
            pdf_file = self.pdf_dir / f"HSK-Level{level}-Version*.pdf"
            matching_files = list(self.pdf_dir.glob(f"HSK-Level{level}-*.pdf"))

            if matching_files:
                pdf_path = matching_files[0]
                logger.info(f"Extracting HSK Level {level} from {pdf_path.name}")
                try:
                    content = self.extract_pdf(str(pdf_path), level)
                    results[f"level_{level}"] = content
                    logger.info(f"✓ HSK Level {level} extracted successfully")
                except Exception as e:
                    logger.error(f"✗ Failed to extract HSK Level {level}: {e}")
                    results[f"level_{level}"] = {"error": str(e)}
            else:
                logger.warning(f"No PDF found for HSK Level {level}")
                results[f"level_{level}"] = {"error": "PDF not found"}

        return results

    def extract_pdf(self, pdf_path: str, level: int) -> Dict:
        """
        Extract text and structure from a single PDF.

        Args:
            pdf_path: Path to the PDF file
            level: HSK level (for metadata)

        Returns:
            Dictionary with extracted content and metadata
        """
        pdf_path = Path(pdf_path)
        content = {
            "level": level,
            "source_file": pdf_path.name,
            "total_pages": 0,
            "text": "",
            "structured_content": {
                "lessons": [],
                "vocabulary": [],
                "grammar": [],
                "examples": [],
                "strokes": [],
                "radicals": []
            },
            "metadata": {}
        }

        try:
            # Get total pages and metadata
            with open(pdf_path, 'rb') as f:
                reader = pypdf.PdfReader(f)
                content["total_pages"] = len(reader.pages)

                if reader.metadata:
                    content["metadata"] = {
                        "title": reader.metadata.get("/Title", ""),
                        "author": reader.metadata.get("/Author", ""),
                        "subject": reader.metadata.get("/Subject", ""),
                    }

            # Extract text using pdfplumber for better structure
            with pdfplumber.open(pdf_path) as pdf:
                full_text = ""

                for page_num, page in enumerate(pdf.pages, 1):
                    page_text = page.extract_text()
                    if page_text:
                        full_text += f"\n--- Page {page_num} ---\n{page_text}"

                        # Try to extract tables (often used for vocab/grammar)
                        tables = page.extract_tables()
                        if tables:
                            for table in tables:
                                full_text += f"\n[TABLE]\n"
                                for row in table:
                                    full_text += " | ".join(str(cell) if cell else "" for cell in row) + "\n"

                content["text"] = full_text

        except Exception as e:
            logger.error(f"Error extracting PDF {pdf_path}: {e}")
            content["error"] = str(e)

        # Save extracted text
        output_file = self.text_dir / f"HSK_Level{level}_extracted.txt"
        with open(output_file, 'w', encoding='utf-8') as f:
            f.write(content["text"])
        logger.info(f"Saved extracted text to {output_file}")

        return content

    def parse_structured_content(self, raw_text: str, level: int) -> Dict:
        """
        Parse raw text into structured HSK content (vocabulary, grammar, etc.).
        This is a heuristic parser - can be improved with ML.

        Args:
            raw_text: Raw extracted text from PDF
            level: HSK level

        Returns:
            Dictionary with structured content
        """
        structured = {
            "vocabulary": [],
            "grammar": [],
            "examples": [],
            "lessons": []
        }

        lines = raw_text.split('\n')
        current_lesson = None

        # Simple heuristic parsing (can be enhanced)
        for i, line in enumerate(lines):
            line = line.strip()

            # Detect lesson headers
            if 'lesson' in line.lower() or 'unit' in line.lower():
                current_lesson = {
                    "title": line,
                    "content": []
                }
                structured["lessons"].append(current_lesson)

            # Detect grammar sections
            elif 'grammar' in line.lower() or '语法' in line:
                structured["grammar"].append({
                    "content": line,
                    "context": current_lesson["title"] if current_lesson else "Unknown"
                })

            # Detect vocabulary sections
            elif 'vocabulary' in line.lower() or '词汇' in line or '单词' in line:
                structured["vocabulary"].append({
                    "content": line,
                    "context": current_lesson["title"] if current_lesson else "Unknown"
                })

            # Detect example sentences
            elif any(indicator in line.lower() for indicator in ['example:', 'sentence:', '例句']):
                structured["examples"].append({
                    "content": line,
                    "context": current_lesson["title"] if current_lesson else "Unknown"
                })

        return structured

    def save_extracted_data(self, results: Dict, format: str = "json"):
        """
        Save extracted data to file.

        Args:
            results: Extraction results dictionary
            format: Output format ('json' or 'txt')
        """
        if format == "json":
            output_file = self.output_dir / "hsk_extracted_data.json"
            with open(output_file, 'w', encoding='utf-8') as f:
                json.dump(results, f, ensure_ascii=False, indent=2)
            logger.info(f"Saved JSON data to {output_file}")

        elif format == "txt":
            output_file = self.output_dir / "hsk_extracted_summary.txt"
            with open(output_file, 'w', encoding='utf-8') as f:
                for level, content in results.items():
                    f.write(f"\n{'='*60}\n")
                    f.write(f"{level.upper()}\n")
                    f.write(f"{'='*60}\n")

                    if "error" in content:
                        f.write(f"ERROR: {content['error']}\n")
                    else:
                        f.write(f"Source: {content.get('source_file', 'Unknown')}\n")
                        f.write(f"Pages: {content.get('total_pages', 'Unknown')}\n")
                        f.write(f"Text Length: {len(content.get('text', ''))} characters\n")

            logger.info(f"Saved summary to {output_file}")


def main():
    """Example usage."""
    extractor = HSKPDFExtractor("HSK-Textbooks")

    # Extract all levels
    results = extractor.extract_all_levels([1, 2, 3])

    # Save results
    extractor.save_extracted_data(results, format="json")
    extractor.save_extracted_data(results, format="txt")

    print("✓ PDF extraction complete!")


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    main()
