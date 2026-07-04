"""Local AST retrieval (v0.5): parse code with tree-sitter, return only the
relevant symbol slices instead of dumping whole files. Zero API tokens,
deterministic, exact (no paraphrase) -- the quality-safe cousin of compression.
"""
from .ast_index import Symbol, extract_file, build_index, save_index, load_index
from .retrieve import retrieve
from .text_index import chunk_document, build_text_index, retrieve_text
from .pdf import extract_pdf_text, build_pdf_index

__all__ = ["Symbol", "extract_file", "build_index", "save_index", "load_index", "retrieve", "build_text_index", "retrieve_text", "chunk_document", "extract_pdf_text", "build_pdf_index"]
