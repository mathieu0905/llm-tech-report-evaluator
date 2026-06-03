#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import re
from pathlib import Path


def clean_text(text: str) -> str:
    text = text.replace("\x00", "")
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def safe_slug(path: Path) -> str:
    return path.stem.replace(".", "_").replace(" ", "_")


def first_nonempty_lines(text: str, count: int = 20) -> list[str]:
    lines = [line.strip() for line in text.splitlines()]
    return [line for line in lines if line][:count]


def extract_abstract(text: str) -> str:
    patterns = [
        r"Abstract\s*(.+?)(?:\n\s*1\s+Introduction|\n\s*Introduction|\n\s*1\.)",
        r"ABSTRACT\s*(.+?)(?:\n\s*1\s+Introduction|\n\s*Introduction|\n\s*1\.)",
    ]
    for pattern in patterns:
        match = re.search(pattern, text, flags=re.IGNORECASE | re.DOTALL)
        if match:
            return clean_text(match.group(1))[:4000]
    return ""


def extract_with_fitz(pdf_path: Path, text_dir: Path, img_dir: Path, render_pages: bool) -> dict:
    import fitz  # type: ignore

    doc = fitz.open(pdf_path)
    page_texts = []
    for i, page in enumerate(doc):
        page_text = clean_text(page.get_text("text"))
        page_texts.append(f"\n\n--- PAGE {i + 1} ---\n{page_text}")
    full_text = clean_text("\n".join(page_texts))
    (text_dir / f"{safe_slug(pdf_path)}.txt").write_text(full_text, encoding="utf-8")

    rendered: list[str] = []
    if render_pages and len(doc):
        pages = sorted(set([0, 1, max(0, len(doc) // 2), max(0, len(doc) - 1)]))
        for page_number in pages:
            page = doc[page_number]
            pix = page.get_pixmap(matrix=fitz.Matrix(0.8, 0.8), alpha=False)
            out = img_dir / f"{safe_slug(pdf_path)}_p{page_number + 1}.png"
            pix.save(out)
            rendered.append(str(out))

    metadata = doc.metadata or {}
    first_page_text = clean_text(doc[0].get_text("text")) if len(doc) else ""
    summary = {
        "file": pdf_path.name,
        "pages": len(doc),
        "metadata_title": metadata.get("title", ""),
        "metadata_author": metadata.get("author", ""),
        "first_lines": first_nonempty_lines(first_page_text),
        "abstract": extract_abstract(full_text),
        "toc": doc.get_toc(simple=True)[:80],
        "rendered_pages": rendered,
        "char_count": len(full_text),
        "word_like_count": len(re.findall(r"\w+", full_text)),
    }
    doc.close()
    return summary


def extract_with_pypdf(pdf_path: Path, text_dir: Path) -> dict:
    from pypdf import PdfReader  # type: ignore

    reader = PdfReader(str(pdf_path))
    page_texts = []
    for i, page in enumerate(reader.pages):
        page_text = clean_text(page.extract_text() or "")
        page_texts.append(f"\n\n--- PAGE {i + 1} ---\n{page_text}")
    full_text = clean_text("\n".join(page_texts))
    (text_dir / f"{safe_slug(pdf_path)}.txt").write_text(full_text, encoding="utf-8")
    metadata = reader.metadata or {}
    first_page_text = clean_text(reader.pages[0].extract_text() or "") if reader.pages else ""
    return {
        "file": pdf_path.name,
        "pages": len(reader.pages),
        "metadata_title": str(metadata.get("/Title", "") or ""),
        "metadata_author": str(metadata.get("/Author", "") or ""),
        "first_lines": first_nonempty_lines(first_page_text),
        "abstract": extract_abstract(full_text),
        "toc": [],
        "rendered_pages": [],
        "char_count": len(full_text),
        "word_like_count": len(re.findall(r"\w+", full_text)),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Extract local PDF technical reports for evaluation.")
    parser.add_argument("directory", nargs="?", default=".", help="Directory containing PDF files.")
    parser.add_argument("--output", default="analysis", help="Output directory relative to directory.")
    parser.add_argument("--render-pages", action="store_true", help="Render representative page PNGs when PyMuPDF is available.")
    args = parser.parse_args()

    root = Path(args.directory).resolve()
    out = root / args.output
    text_dir = out / "text"
    img_dir = out / "pages"
    text_dir.mkdir(parents=True, exist_ok=True)
    img_dir.mkdir(parents=True, exist_ok=True)

    pdfs = sorted(root.glob("*.pdf"))
    summaries = []
    try:
        import fitz  # noqa: F401

        for pdf_path in pdfs:
            summaries.append(extract_with_fitz(pdf_path, text_dir, img_dir, args.render_pages))
    except ModuleNotFoundError:
        try:
            import pypdf  # noqa: F401
        except ModuleNotFoundError as exc:
            raise SystemExit(
                "Missing PDF dependency. Install one of: `pip install pymupdf` "
                "or `pip install pypdf`."
            ) from exc
        for pdf_path in pdfs:
            summaries.append(extract_with_pypdf(pdf_path, text_dir))

    (out / "pdf_summaries.json").write_text(
        json.dumps(summaries, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(f"Extracted {len(summaries)} PDFs into {out}")


if __name__ == "__main__":
    main()
