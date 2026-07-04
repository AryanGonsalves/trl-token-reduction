"""PDF -> text so documents get the retrieval lever too. Extracts text per page
(pypdf), then feeds the general text retriever. Scanned/image PDFs need OCR
first (out of scope; text-layer PDFs work). Vision tokens are a separate problem."""
from __future__ import annotations
import os
from typing import Dict


def extract_pdf_text(path: str) -> str:
    from pypdf import PdfReader
    reader = PdfReader(path)
    parts = []
    for i, page in enumerate(reader.pages):
        try:
            t = page.extract_text() or ""
        except Exception:
            t = ""
        if t.strip():
            parts.append(f"[page {i+1}]\n{t}")
    return "\n\n".join(parts)


def build_pdf_index(paths, **kw) -> Dict:
    """paths: list of .pdf files (or .txt). Returns a text index over their content."""
    from .text_index import build_text_index
    docs = {}
    for p in paths:
        if p.lower().endswith(".pdf"):
            docs[os.path.basename(p)] = extract_pdf_text(p)
        else:
            with open(p, encoding="utf-8", errors="replace") as f:
                docs[os.path.basename(p)] = f.read()
    return build_text_index(docs, **kw)
