"""Deterministic retriever with OPTIONAL semantic rerank.

Base (always on, zero deps): identifier/keyword overlap + 1-hop call-graph
expansion -> exact source slices, token-budgeted. When a local embedder is
available (see embed.py), we also rerank candidates by semantic similarity so
vague queries ("users typing too fast" -> rate-limiting code) surface symbols
whose *names* don't keyword-match. Embeddings only re-order; slices stay exact."""
from __future__ import annotations

import re
from typing import Dict, List

from ..util import count_tokens

_WORD = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")


def _tokens(text: str):
    out = set()
    for w in _WORD.findall(text):
        out.add(w.lower())
        for part in re.split(r"_|(?<=[a-z0-9])(?=[A-Z])", w):
            if len(part) >= 3:
                out.add(part.lower())
    return out


def _score(sym, q: set) -> float:
    name_t = _tokens(sym.name)
    ref_t = {r.lower() for r in sym.refs}
    s = 5.0 * len(q & name_t) + 1.0 * len(q & ref_t)
    s += 0.25 * min(len(q & _tokens(sym.source[:800])), 8)
    return s


def _repr(sym) -> str:
    # richer text for the embedder: signature + docstring/first lines (not just 3)
    head = "\n".join(sym.source.splitlines()[:15])
    return f"{sym.name} {sym.kind} {' '.join(sorted(sym.refs))}\n{head}"


def _cos(a, b) -> float:
    dot = sum(x * y for x, y in zip(a, b))
    na = sum(x * x for x in a) ** 0.5
    nb = sum(y * y for y in b) ** 0.5
    return dot / (na * nb) if na and nb else 0.0


def retrieve(index: Dict, query: str, token_budget: int = 1500, k: int = 8,
             expand: bool = True, rerank: bool = True, embedder=None) -> Dict:
    syms = index["symbols"]
    q = _tokens(query)
    kw = [(_score(s, q), s) for s in syms]
    kw_max = max((sc for sc, _ in kw), default=0.0) or 1.0

    if rerank:
        if embedder is None:
            from .embed import get_embedder
            embedder = get_embedder()
        if embedder is not None:
            # cache symbol embeddings on the index (compute once per process)
            if "_emb" not in index or len(index["_emb"]) != len(syms):
                index["_emb"] = embedder([_repr(s) for s in syms])
            qv = embedder([query])[0]
            blended = []
            for (sc, s), sv in zip(kw, index["_emb"]):
                cos01 = (_cos(qv, sv) + 1.0) / 2.0
                blended.append((sc / kw_max + 0.6 * cos01, s))
            scored = sorted(blended, key=lambda x: (-x[0], x[1].start_line))
        else:
            scored = sorted(kw, key=lambda x: (-x[0], x[1].start_line))
    else:
        scored = sorted(kw, key=lambda x: (-x[0], x[1].start_line))

    picked, ids = [], set()

    def add(s):
        if s.id not in ids:
            ids.add(s.id); picked.append(s)

    for sc, s in scored:
        if len(picked) >= k or sc <= 0:
            break
        add(s)

    if expand and picked:
        by_name: Dict[str, List] = {}
        for s in syms:
            by_name.setdefault(s.name, []).append(s)
        for s in list(picked):
            for callee in s.refs:
                for t in by_name.get(callee, []):
                    if len(picked) < k:
                        add(t)
            for t in syms:
                if s.name in t.refs and len(picked) < k:
                    add(t)

    out, used, chosen = [], 0, []
    for s in picked:
        block = f"# {s.file}:{s.start_line}-{s.end_line}  ({s.kind} {s.name})\n{s.source}"
        t = count_tokens(block)
        if used + t > token_budget and chosen:
            break
        out.append(block); used += t; chosen.append(s)
    return {"context": "\n\n".join(out), "symbols": chosen, "tokens": used}
