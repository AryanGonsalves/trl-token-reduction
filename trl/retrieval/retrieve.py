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

# Fix candidate (opt-in): keyword scoring alone ranks keyword-dense TEST/spec files
# above the real definition (e.g. `test_extract_and_retrieve` > the `retrieve` def).
# Deprioritizing non-impl paths lets the actual implementation surface. Multiplier,
# not a filter -- test files can still win when nothing in the impl matches.
_NONIMPL = re.compile(r"(^|/)tests?/|(^|/)test_|_test\.py$|(^|/)(validate|bench)/")
_TEST_PENALTY = 0.35
_ADAPTIVE_CEIL = 6000   # hard cap on adaptive_budget expansion


def _is_nonimpl(path: str) -> bool:
    return bool(_NONIMPL.search(path.replace("\\", "/")))


# Fix #3 (cheap, opt-in): expand the searchable representation with each symbol's
# signature + leading comments + docstring, so a NATURAL-LANGUAGE query can match
# the prose describing what a function does even when it misses the identifier.
_TRIPLE = re.compile(r'("""|\'\'\')(.*?)(\1)', re.S)
_COMMENT = re.compile(r'^[#/*\-\s]+')
_W_DOC = 1.5


def _doc_text(source: str) -> str:
    lines = source.splitlines()
    parts = [lines[0]] if lines else []            # signature line
    for ln in lines[1:16]:                          # leading comment lines
        st = ln.strip()
        if st.startswith(("#", "//", "///", "*", "/*", "--", ";;")):
            parts.append(_COMMENT.sub("", st))
    m = _TRIPLE.search(source)                       # first docstring block
    if m:
        parts.append(m.group(2))
    return " ".join(parts)


# Fix (opt-in, FREE, no model): expand a natural-language query into likely code
# identifiers before scoring -- drop stopwords, add camel/snake parts + adjacent
# joins, and a small hand-curated domain synonym map. Deterministic. Curated to
# this project's vocabulary, so treat generalization with care.
_STOP = {"the", "a", "an", "of", "to", "is", "are", "how", "do", "does", "we",
         "in", "on", "for", "with", "and", "or", "that", "this", "it", "its",
         "be", "by", "as", "at", "from", "what", "which", "when", "where", "why",
         "use", "used", "using", "not", "no", "never", "only", "also", "into",
         "make", "sure", "gets", "getting", "whole", "part", "instead", "silently",
         "important", "without", "calling", "answered", "billed"}
_SYN = {
    "number": ("fact", "preserve"), "numbers": ("fact", "preserve"),
    "amount": ("fact",), "id": ("fact",), "ids": ("fact",),
    "drop": ("preserve",), "drops": ("preserve",), "dropped": ("preserve",),
    "lose": ("preserve",), "losing": ("preserve",), "guard": ("preserve",),
    "guarantee": ("preserve",), "compressor": ("compress", "preserve"),
    "easy": ("cascade", "route"), "simple": ("cascade", "route"),
    "cheap": ("cascade",), "escalate": ("cascade",), "expensive": ("cascade",),
    "local": ("cascade", "route"), "question": ("cascade",),
    "fetch": ("retrieve",), "get": ("retrieve",), "slice": ("retrieve",),
    "slices": ("retrieve",), "chunk": ("retrieve",), "chunks": ("retrieve",),
    "chosen": ("retrieve",), "choose": ("retrieve",), "select": ("retrieve",),
    "cache": ("prefix", "stable"), "cached": ("cache", "prefix", "stable"),
    "cheaper": ("cache",), "caching": ("cache", "prefix"), "prompt": ("prefix",),
    "reuse": ("cache",), "prefix": ("stable",),
}


def _expand_query(query: str):
    q = set(_tokens(query)) - _STOP
    for t in list(q):
        q.update(_SYN.get(t, ()))
    seq = [w.lower() for w in _WORD.findall(query) if w.lower() not in _STOP]
    for a, b in zip(seq, seq[1:]):
        q.add(f"{a}_{b}"); q.add(f"{a}{b}")   # camel/snake compound guesses
    return q


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


def _default_local_ask():
    """Default LOCAL rerank provider: ollama llama3.2:3b @ localhost:11434,
    overridable via config.yaml [rerank] or env (TRL_RERANK_MODEL / _ENDPOINT), so
    run_*.bat works out of the box. Transport errors surface at CALL time, so the
    caller fails safe to keyword ranking. Returns None only if construction fails."""
    import os
    model = os.environ.get("TRL_RERANK_MODEL")
    endpoint = os.environ.get("TRL_RERANK_ENDPOINT")
    if not (model and endpoint):
        try:
            from ..util import load_config
            rc = (load_config() or {}).get("rerank", {}) or {}
        except Exception:
            rc = {}
        model = model or rc.get("local_model", "llama3.2:3b")
        endpoint = endpoint or rc.get("endpoint", "http://localhost:11434")
    try:
        from ..local_model import LocalModel
        return LocalModel({"provider": "ollama", "model": model,
                           "endpoint": endpoint}).ask
    except Exception:
        return None


def _hosted_ask():
    """Hosted rerank ask via Anthropic using the USER'S OWN ANTHROPIC_API_KEY and
    the model from config.yaml [rerank] (env TRL_RERANK_MODEL overrides). Returns
    None -> keyword fallback if there's no key or the SDK is missing; API errors
    surface at CALL time so the caller fails safe. NEVER spends unless the caller
    explicitly passes rerank="hosted"."""
    import os
    if not os.environ.get("ANTHROPIC_API_KEY"):
        return None
    model = os.environ.get("TRL_RERANK_MODEL")
    if not model:
        try:
            from ..util import load_config
            model = (load_config() or {}).get("rerank", {}).get(
                "model", "claude-haiku-4-5-20251001")
        except Exception:
            model = "claude-haiku-4-5-20251001"
    try:
        import anthropic
        client = anthropic.Anthropic()
    except Exception:
        return None

    def ask(prompt):
        r = client.messages.create(model=model, max_tokens=64,
                                   messages=[{"role": "user", "content": prompt}])
        return "".join(b.text for b in r.content if getattr(b, "type", "") == "text")
    return ask


def retrieve(index: Dict, query: str, token_budget: int = 1500, k: int = 8,
             expand: bool = True, rerank: bool = True, embedder=None,
             min_similarity: float = 0.10, deprioritize_tests: bool = True,
             adaptive_budget: bool = True, doc_boost: bool = False,
             expand_query: bool = False, ask=None, local_model=None,
             rerank_shortlist: int = 30) -> Dict:
    # Code-retrieval defaults: deprioritize_tests + adaptive_budget ON (the
    # near-free 6/6 win). Pass both False to restore the strict legacy behavior.
    syms = index["symbols"]
    q = _expand_query(query) if expand_query else _tokens(query)
    if doc_boost:
        kw = [(_score(s, q) + _W_DOC * min(len(q & _tokens(_doc_text(s.source))), 8), s)
              for s in syms]
    else:
        kw = [(_score(s, q), s) for s in syms]
    if deprioritize_tests:
        # re-weight (never drop): demote test/spec/bench slices so a real
        # definition that also matches ranks above them.
        kw = [(sc * (_TEST_PENALTY if _is_nonimpl(s.file) else 1.0), s) for sc, s in kw]
    kw_max = max((sc for sc, _ in kw), default=0.0) or 1.0

    # `scored` entries are (rank_key, admissible, symbol). `admissible` is the
    # relevance gate: a symbol is only picked if it actually matches. For the
    # keyword path that's score > 0 (as before). For the rerank path a symbol
    # can also qualify on SEMANTIC similarity alone (its name need not keyword-
    # match) -- but must clear `min_similarity` raw cosine, otherwise an
    # unrelated query would still fill k slots with near-orthogonal noise
    # (blended score is never <= 0, so the old `sc <= 0` cutoff never fired).
    if rerank in ("local", "hosted"):
        # OPT-IN LLM-rerank. "local" = ollama ($0); "hosted" = Anthropic with the
        # user's OWN key (claude-haiku-4-5 by default, per config.yaml [rerank]).
        # Shortlist by keyword, ask the model to reorder, FAIL SAFE to keyword
        # ranking on ANY error (no key, unreachable, API error). Never crash; never
        # spend unless rerank="hosted" is explicitly requested with a key present.
        if ask is not None:
            _ask = ask
        elif rerank == "hosted":
            _ask = _hosted_ask()                 # Anthropic, user's own key
        else:
            _ask = getattr(local_model, "ask", None) or _default_local_ask()
        scored = None
        if _ask is not None:
            failed = {"x": False}

            def _guard(prompt, _a=_ask):
                try:
                    return _a(prompt)
                except Exception:
                    failed["x"] = True           # record so we fall back to keyword
                    raise

            try:
                from .llm_rerank import llm_rerank
                kw_sorted = [s for _, s in sorted(kw, key=lambda x: (-x[0], x[1].start_line))]
                reordered = llm_rerank(query, kw_sorted, k, _guard, shortlist=rerank_shortlist)
                if not failed["x"]:
                    # ONLY when the model actually answered: its picks become
                    # admissible + top-ranked; everything else keeps its keyword
                    # admissibility. If the ask raised, llm_rerank returned a keyword
                    # backfill -- we IGNORE it (failed=True) and fall through to the
                    # pure keyword ranking below, so fail-safe == keyword exactly.
                    order = {id(s): r for r, s in enumerate(reordered)}
                    scored = [((1e6 - order[id(s)], True, s) if id(s) in order
                               else (sc, sc > 0, s)) for sc, s in kw]
            except Exception:
                scored = None
        if scored is None:
            scored = [(sc, sc > 0, s) for sc, s in kw]   # unreachable/failed -> keyword
    elif rerank:
        if embedder is None:
            from .embed import get_embedder
            embedder = get_embedder()
        if embedder is not None:
            # cache symbol embeddings on the index (compute once per process)
            if "_emb" not in index or len(index["_emb"]) != len(syms):
                index["_emb"] = embedder([_repr(s) for s in syms])
            qv = embedder([query])[0]
            scored = []
            for (sc, s), sv in zip(kw, index["_emb"]):
                cos = _cos(qv, sv)
                blended = sc / kw_max + 0.6 * ((cos + 1.0) / 2.0)
                admissible = sc > 0 or cos >= min_similarity
                scored.append((blended, admissible, s))
        else:
            scored = [(sc, sc > 0, s) for (sc, s) in kw]
    else:
        scored = [(sc, sc > 0, s) for (sc, s) in kw]
    scored.sort(key=lambda x: (-x[0], x[2].start_line))

    picked, ids = [], set()

    def add(s):
        if s.id not in ids:
            ids.add(s.id); picked.append(s)

    for rank_key, admissible, s in scored:
        if len(picked) >= k:
            break
        if not admissible:      # skip irrelevant; keyword path stays sorted so
            continue            # this is equivalent to the old sc<=0 break
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

    blocks = []
    for s in picked:
        block = f"# {s.file}:{s.start_line}-{s.end_line}  ({s.kind} {s.name})\n{s.source}"
        blocks.append((block, count_tokens(block), s))

    # Fix #2 (opt-in): a tight budget cuts large real defs (a 78-line function is
    # ~730 tok, so under an 800 budget only a rank-1 slice fits). adaptive_budget
    # grows the effective budget to fit the top few ranked slices, capped, so the
    # best matches are never starved. Default off keeps the conservative behavior.
    eff_budget = token_budget
    if adaptive_budget and blocks:
        need = sum(t for _, t, _ in blocks[:3])
        eff_budget = min(_ADAPTIVE_CEIL, max(token_budget, need))

    out, used, chosen = [], 0, []
    for block, t, s in blocks:
        # `and chosen`: the top-ranked slice is always emitted even if it alone
        # exceeds the budget -- we never return an empty context.
        if used + t > eff_budget and chosen:
            break
        out.append(block); used += t; chosen.append(s)
    return {"context": "\n\n".join(out), "symbols": chosen, "tokens": used}
