"""
Extract each page of the HSK textbook PDFs as a standalone PNG image.

The HSK PDFs have no text layer -- every page is a single scanned image
embedded as a PDF XObject. This script pulls that embedded image out
losslessly (no re-rendering/re-compression) so later steps can read the
page images directly for vision-based transcription.
"""

import json
from pathlib import Path

import pypdf

ROOT = Path(__file__).resolve().parent.parent
PDF_DIR = ROOT / "HSK-Textbooks"
OUT_DIR = ROOT / "hsk_data" / "page_images"

BOOKS = {
    1: "HSK-Level1-Version2.0.pdf",
    2: "HSK-Level2-Version2.0.pdf",
    3: "HSK-Level3-Version2.0.pdf",
}


def extract_book(level: int, filename: str) -> dict:
    pdf_path = PDF_DIR / filename
    out_dir = OUT_DIR / f"level{level}"
    out_dir.mkdir(parents=True, exist_ok=True)

    reader = pypdf.PdfReader(str(pdf_path))
    n_pages = len(reader.pages)
    pages_written = []

    for i, page in enumerate(reader.pages):
        images = list(page.images)
        page_num = i + 1
        fname = f"page_{page_num:03d}.png"
        out_path = out_dir / fname

        if len(images) == 1:
            images[0].image.save(out_path)
            pages_written.append({"pdf_page": page_num, "file": fname, "mode": "single_image"})
        elif len(images) == 0:
            pages_written.append({"pdf_page": page_num, "file": None, "mode": "no_image_found"})
        else:
            # Multiple embedded images on one page: save the largest (by pixel area)
            # as the page image; this has not been observed in these books but is
            # handled defensively.
            best = max(images, key=lambda im: im.image.size[0] * im.image.size[1])
            best.image.save(out_path)
            pages_written.append({
                "pdf_page": page_num,
                "file": fname,
                "mode": f"multi_image_took_largest_of_{len(images)}",
            })

    return {
        "level": level,
        "source_file": filename,
        "total_pages": n_pages,
        "pages": pages_written,
    }


def main():
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    manifest = {}
    for level, filename in BOOKS.items():
        print(f"Extracting HSK Level {level} from {filename} ...")
        result = extract_book(level, filename)
        manifest[f"level{level}"] = result
        n_ok = sum(1 for p in result["pages"] if p["file"])
        print(f"  {n_ok}/{result['total_pages']} pages extracted -> hsk_data/page_images/level{level}/")

    manifest_path = OUT_DIR / "manifest.json"
    with open(manifest_path, "w", encoding="utf-8") as f:
        json.dump(manifest, f, ensure_ascii=False, indent=2)
    print(f"\nManifest written to {manifest_path}")


if __name__ == "__main__":
    main()
