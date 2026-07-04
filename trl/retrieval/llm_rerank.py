"""LLM-based rerank: when keyword + embeddings miss a vague query, ask a cheap
model to pick the relevant symbols from a shortlist. One call, no per-candidate
cost. `ask` is any callable(prompt:str)->str. Returns reordered symbols."""
from __future__ import annotations
import re
from typing import Callable, List


def _line(sym) -> str:
    doc = ""
    for ln in sym.source.splitlines()[1:6]:
        t = ln.strip().strip('"').strip("#").strip()
        if len(t) > 8:
            doc = t; break
    return f"{sym.name} ({sym.kind}) - {doc[:100]}"


def llm_rerank(query: str, symbols: List, k: int, ask: Callable[[str], str],
               shortlist: int = 200) -> List:
    cands = symbols[:shortlist]
    listing = "\n".join(f"{i}. {_line(s)}" for i, s in enumerate(cands))
    prompt = (f"Question: {query}\n\nCandidate code symbols:\n{listing}\n\n"
              f"Return ONLY the numbers of the up-to-{k} MOST relevant symbols for the "
              f"question, comma-separated, best first. Numbers only.")
    try:
        out = ask(prompt)
    except Exception:
        return symbols[:k]
    # dedupe while keeping the model's order (a chatty model may repeat numbers)
    idxs = list(dict.fromkeys(
        int(x) for x in re.findall(r"\d+", out) if int(x) < len(cands)))
    picked = [cands[i] for i in idxs][:k]
    seen = {id(s) for s in picked}
    for s in symbols:                      # backfill if the model returned too few
        if len(picked) >= k:
            break
        if id(s) not in seen:
            picked.append(s)
    return picked
