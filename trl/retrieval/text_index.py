"""General document/text retrieval -- the prose sibling of the code retriever.

Chunk arbitrary long text (a pasted document, an extracted PDF, a knowledge base)
into passages, then return ONLY the passages relevant to a question instead of
stuffing the whole document into context. Same 'retrieve, don't stuff' lever,
now for any text. Keyword + optional embedding rerank (shared with the code path).
Passages are verbatim -> exact, no paraphrase, quality-safe."""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Dict, List

from ..util import count_tokens
from .retrieve import _tokens, _cos

_NUM = re.compile(r"\d+")


def _ttokens(text):
    return _tokens(text) | set(_NUM.findall(text))


@dataclass
class Chunk:
    id: str
    text: str
    source: str
    idx: int
    start_line: int


def chunk_document(text: str, source: str = "doc",
                   target_chars: int = 700, overlap_paras: int = 1) -> List[Chunk]:
    """Split on blank lines into paragraphs, then pack paragraphs into ~target_chars
    chunks with a small paragraph overlap so a fact on a boundary is never lost."""
    lines = text.splitlines()
    # paragraph = run of non-blank lines; track its starting line number
    paras, cur, start = [], [], 1
    for i, ln in enumerate(lines, 1):
        if ln.strip() == "":
            if cur:
                paras.append((start, "\n".join(cur))); cur = []
        else:
            if not cur:
                start = i
            cur.append(ln)
    if cur:
        paras.append((start, "\n".join(cur)))

    chunks: List[Chunk] = []
    i = 0
    while i < len(paras):
        buf, sl, n = [], paras[i][0], 0
        j = i
        while j < len(paras) and (n == 0 or n + len(paras[j][1]) <= target_chars):
            buf.append(paras[j][1]); n += len(paras[j][1]) + 2; j += 1
        chunks.append(Chunk(f"{source}#{len(chunks)}", "\n\n".join(buf), source,
                            len(chunks), sl))
        if j >= len(paras):
            break
        i = max(j - overlap_paras, i + 1)      # advance with small overlap
    return chunks


def build_text_index(docs: Dict[str, str], **kw) -> Dict:
    """docs: {source_name: text}. Returns {chunks: [...]}"""
    chunks: List[Chunk] = []
    for src, text in docs.items():
        chunks.extend(chunk_document(text, src, **kw))
    return {"chunks": chunks}


def _score(chunk: Chunk, q: set) -> float:
    return len(q & _ttokens(chunk.text))


def retrieve_text(index: Dict, query: str, token_budget: int = 1200, k: int = 6,
                  rerank: bool = True, embedder=None) -> Dict:
    chunks = index["chunks"]
    q = _ttokens(query)
    if not q:                       # empty/whitespace query -> nothing (parity
        return {"context": "", "chunks": [], "tokens": 0}   # with code retrieve()
    kw = [(float(_score(c, q)), c) for c in chunks]
    kw_max = max((s for s, _ in kw), default=0.0) or 1.0

    if rerank:
        if embedder is None:
            from .embed import get_embedder
            embedder = get_embedder()
        if embedder is not None:
            if "_emb" not in index or len(index["_emb"]) != len(chunks):
                index["_emb"] = embedder([c.text[:600] for c in chunks])
            qv = embedder([query])[0]
            scored = sorted(
                ((s / kw_max + 0.6 * ((_cos(qv, cv) + 1) / 2), c)
                 for (s, c), cv in zip(kw, index["_emb"])),
                key=lambda x: (-x[0], x[1].idx))
        else:
            scored = sorted(kw, key=lambda x: (-x[0], x[1].idx))
    else:
        scored = sorted(kw, key=lambda x: (-x[0], x[1].idx))

    out, used, chosen = [], 0, []
    for sc, c in scored:
        if len(chosen) >= k or (sc <= 0 and chosen):
            break
        block = f"# {c.source} (chunk {c.idx}, line {c.start_line})\n{c.text}"
        t = count_tokens(block)
        if used + t > token_budget and chosen:
            break
        out.append(block); used += t; chosen.append(c)
    return {"context": "\n\n".join(out), "chunks": chosen, "tokens": used}
