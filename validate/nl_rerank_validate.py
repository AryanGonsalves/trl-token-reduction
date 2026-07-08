"""Validate the OPT-IN local/hosted LLM-rerank lever (`retrieve(rerank="local")`).

Modes:
  (default)   local $0 single run via ollama llama3.2:3b
  --paid      single run via Anthropic (capped)
  --eval      RIGOROUS: Haiku 4.5 + Sonnet 5, NL + loop, N runs each, mean/min/max,
              non-inferiority, verdict. HARD cost cap $1.50.
  --selftest  offline proof (fake ask, no anthropic import): plumbing + the cost cap.

Rerank is OFF by default in retrieve(); this harness is the only thing that turns it
on. Claude never spends -- Aryan runs the paid modes.
"""
import os, re, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from trl.retrieval import build_index, retrieve
from trl.local_model import LocalModel

# --- Honest NL set: gold symbols spread across the codebase; natural questions a
# --- real user/agent would ask, NO symbol name in the query, and NOT reusing the
# --- doc_boost/expand_query curated synonym vocabulary. (query, gold, gold_file)
NL = [
    ("how do we keep exact dollar values from disappearing when we shorten text?", "_preserve_facts", "trl/compress.py"),
    ("when a request is trivial, how do we handle it on the small model to avoid paying for the big one?", "cascade", "trl/cascade.py"),
    ("which leading part of the messages stays identical every turn so it only needs paying for once?", "stable_prefix", "trl/cache.py"),
    ("how far back into the history can we treat as unchanged and reusable across steps?", "cacheable_prefix", "trl/cache.py"),
    ("how do we pull just the relevant functions from a big project instead of pasting everything?", "retrieve", "trl/retrieval/retrieve.py"),
    ("how do we measure how long a piece of text is for the model, and what if the tokenizer library is missing?", "count_tokens", "trl/util.py"),
    ("how do we squeeze the older conversation turns before sending them again?", "compress_request", "trl/compress.py"),
    ("how does the stand-in local model decide which lines to keep when trimming output?", "smart_compress", "trl/local_model.py"),
    ("what removes duplicate log lines and stack-trace noise without any model at all?", "heuristic_compress", "trl/local_model.py"),
    ("how do we scan a folder of source and remember what changed so we don't re-parse everything?", "build_index", "trl/retrieval/ast_index.py"),
    ("how do we pull the functions and classes out of a single source file?", "extract_file", "trl/retrieval/ast_index.py"),
    ("how do we split a long document into overlapping passages?", "chunk_document", "trl/retrieval/text_index.py"),
    ("how do we rewrite a Claude API request to add caching markers and make it smaller?", "transform_anthropic_request", "proxy/transform.py"),
    ("how do we tell whether a line is just a debug or trace log we can throw away?", "_is_boilerplate", "trl/local_model.py"),
    ("how are settings read from the yaml file, and what happens if it isn't there?", "load_config", "trl/util.py"),
]
# Non-inferiority set: the 6 symbol-name queries keyword already nails 6/6.
LOOP = [
    ("how does compress_request fold and shrink the tail?", "compress_request", "trl/compress.py"),
    ("how does cascade decide to answer locally vs escalate?", "cascade", "trl/cascade.py"),
    ("how does _preserve_facts stop the compressor dropping numbers?", "_preserve_facts", "trl/compress.py"),
    ("what does stable_prefix mark for caching?", "stable_prefix", "trl/cache.py"),
    ("how does retrieve rank and budget the code slices?", "retrieve", "trl/retrieval/retrieve.py"),
    ("how does count_tokens fall back without tiktoken?", "count_tokens", "trl/util.py"),
]

MODELS = ["claude-haiku-4-5-20251001", "claude-sonnet-5"]
N_RUNS = int(os.environ.get("TRL_EVAL_RUNS", "2"))
SHORTLIST = 40
CAP_USD = 1.50
MAX_OUTPUT = 64
# Deliberately HIGH prices (>= both models) so the static worst-case over-states cost.
PRICE_IN, PRICE_OUT, TOK_FACTOR, EST_IN = 5.0, 25.0, 1.6, 1700


def _hits(idx, qs, **rk):
    hits, miss = 0, []
    for q, gold, gf in qs:
        idx.pop("_emb", None)
        r = retrieve(idx, q, k=8, **rk)
        if any(s.name == gold and gf in s.file.replace("\\", "/") for s in r["symbols"]):
            hits += 1
        else:
            miss.append(gold)
    return hits, miss


def _worst_case_usd(n_calls):
    return n_calls * (EST_IN * TOK_FACTOR * PRICE_IN + MAX_OUTPUT * PRICE_OUT) / 1e6


def _preflight(n_calls, out=print):
    worst = _worst_case_usd(n_calls)
    out(f"HARD CAP ${CAP_USD:.2f} | static worst-case ${worst:.4f} over <= {n_calls} calls")
    if worst > CAP_USD:
        raise SystemExit(f"ABORT: worst-case ${worst:.2f} exceeds cap ${CAP_USD:.2f}")


def _capped(raw_call, spent):
    def ask(prompt):
        if spent["usd"] + _worst_case_usd(1) > CAP_USD:
            raise RuntimeError("cost cap reached")
        text, usd = raw_call(prompt)
        spent["usd"] += usd
        return text
    return ask


def run_eval(ask_factory, models, n_runs, out=print, idx=None, nl=None, loop=None):
    idx = idx if idx is not None else build_index(".")
    nl = nl if nl is not None else NL
    loop = loop if loop is not None else LOOP
    kw_nl = _hits(idx, nl, rerank=False)[0]
    db_nl = _hits(idx, nl, rerank=False, doc_boost=True)[0]
    kw_loop = _hits(idx, loop, rerank=False)[0]
    out(f"queries: NL={len(nl)} loop={len(loop)}  runs/model={n_runs}  shortlist={SHORTLIST}")
    out(f"baselines (0 model calls): NL keyword={kw_nl}/{len(nl)}  doc_boost={db_nl}/{len(nl)}"
        f"  | loop keyword={kw_loop}/{len(loop)}")
    detail = {}
    for model in models:
        ask = ask_factory(model)
        nls, loops = [], []
        for _ in range(n_runs):
            nls.append(_hits(idx, nl, rerank="local", ask=ask, rerank_shortlist=SHORTLIST)[0])
            loops.append(_hits(idx, loop, rerank="local", ask=ask, rerank_shortlist=SHORTLIST)[0])
        noninf = all(l >= len(loop) for l in loops)
        beats = min(nls) > db_nl
        detail[model] = {"nl": nls, "loop": loops, "beats": beats, "noninf": noninf}
        out(f"\n{model}:")
        out(f"  rerank NL recall: mean={sum(nls)/len(nls):.1f}/{len(nl)} "
            f"min={min(nls)} max={max(nls)} runs={nls}")
        out(f"  loop non-inferiority: {'PASS' if noninf else 'FAIL'} runs={loops} "
            f"(need {len(loop)}/{len(loop)} each run)")
        out(f"  vs doc_boost {db_nl}/{len(nl)}: rerank "
            f"{'RELIABLY BEATS (min > doc_boost)' if beats else 'does NOT reliably beat'}")
    all_beat = all(d["beats"] for d in detail.values())
    all_noninf = all(d["noninf"] for d in detail.values())
    out("\n=== VERDICT ===")
    out(f"rerank reliably beats doc_boost on NL, every run, both models: {all_beat}")
    out(f"loop non-inferiority held every run, both models: {all_noninf}")
    out(f"SHIP rerank='local'?  {'YES' if (all_beat and all_noninf) else 'NO (not worth cost/complexity yet)'}")
    return {"db_nl": db_nl, "kw_nl": kw_nl, "beat": all_beat, "noninf": all_noninf, "detail": detail}


def _writer(path):
    f = open(path, "w", encoding="utf-8")

    def out(line=""):
        print(line)
        f.write(str(line) + "\n"); f.flush()
    return out, f


def _eval_paid():
    import anthropic
    out, f = _writer("nl_rerank_eval_result.txt")
    try:
        _preflight(len(MODELS) * N_RUNS * (len(NL) + len(LOOP)), out)
        client = anthropic.Anthropic()
        spent = {"usd": 0.0}

        def factory(model):
            def raw(prompt):
                r = client.messages.create(model=model, max_tokens=MAX_OUTPUT,
                                           messages=[{"role": "user", "content": prompt}])
                u = r.usage
                usd = (u.input_tokens * PRICE_IN + u.output_tokens * PRICE_OUT) / 1e6
                text = "".join(b.text for b in r.content if getattr(b, "type", "") == "text")
                return text, usd
            return _capped(raw, spent)

        run_eval(factory, MODELS, N_RUNS, out)
        out(f"\nactual spend estimate: ${spent['usd']:.4f} (cap ${CAP_USD:.2f})")
    finally:
        f.close()


def _oracle_factory(nl, loop):
    """Deterministic offline stand-in for a PERFECT reranker: reads the question
    from the prompt and returns the gold symbol's shortlist index if present. Proves
    plumbing + reveals the shortlist-coverage ceiling; NOT evidence of real quality."""
    goldmap = {q: g for q, g, _ in list(nl) + list(loop)}

    def factory(_model):
        def ask(prompt):
            qline = next((l for l in prompt.splitlines() if l.startswith("Question:")), "")
            gold = goldmap.get(qline[len("Question:"):].strip())
            if gold:
                for l in prompt.splitlines():
                    m = re.match(rf"(\d+)\.\s+{re.escape(gold)}\b", l)
                    if m:
                        return m.group(1)
            return "0"
        return ask
    return factory


def _selftest():
    print("== plumbing (oracle fake ask, real repo, offline) ==")
    run_eval(_oracle_factory(NL, LOOP), ["fake-model"], N_RUNS)
    print("\n== cost cap proofs (no anthropic import) ==")
    global CAP_USD
    save = CAP_USD
    CAP_USD = 0.0001
    try:
        _preflight(len(MODELS) * N_RUNS * (len(NL) + len(LOOP)))
        print("CAP FAIL: preflight did not abort")
    except SystemExit:
        print("cap: preflight aborts when worst-case > cap  OK")
    CAP_USD = 0.0
    try:
        _capped(lambda p: ("0", 0.01), {"usd": 0.0})("x")
        print("CAP FAIL: running guard passed")
    except RuntimeError:
        print("cap: running guard blocks over-budget call  OK")
    CAP_USD = save
    print("SELFTEST DONE")


def main():
    if "--selftest" in sys.argv:
        return _selftest()
    if "--eval" in sys.argv:
        if not os.environ.get("ANTHROPIC_API_KEY"):
            print("--eval needs ANTHROPIC_API_KEY (hosted models)."); return
        return _eval_paid()
    # default: local $0 single run
    lm = LocalModel({"provider": "ollama",
                     "model": os.environ.get("TRL_RERANK_MODEL", "llama3.2:3b"),
                     "endpoint": os.environ.get("TRL_RERANK_ENDPOINT", "http://localhost:11434")})
    if not lm.available():
        print("No local ollama model reachable at", lm.endpoint)
        print("Fix: install ollama, `ollama pull llama3.2:3b`, then re-run.")
        print("Or run the rigorous hosted eval:  --eval  (needs ANTHROPIC_API_KEY, capped $1.50)")
        return
    run_eval(lambda _m: lm.ask, ["local-llama3.2:3b"], N_RUNS)


if __name__ == "__main__":
    main()
