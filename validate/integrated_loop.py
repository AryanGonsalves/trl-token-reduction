"""Full-stack INTEGRATED reference path over the REAL repo (this project's code).

Proves the product, not a harness: an agent loops over the real codebase, and the
levers fire AUTOMATICALLY as a request is assembled --
    retrieval   : whole-repo dump  ->  only the relevant AST slices (exact)
    compression : the growing history is summarized (+ deterministic fact guard)
    caching     : the stable prefix is billed once at the cache rate, not full
    cascade     : verifiable lookups answered locally ($0) -- ON only if a local
                  model is reachable; otherwise reported OFF (honest).

Offline measurement only (no API). Token counts use trl.util.count_tokens, which
uses tiktoken when the cl100k BPE file is available and a char/word heuristic
otherwise; the REDUCTION PERCENTAGES are robust to that choice. Real billed tokens
(and cache_creation vs cache_read) are proven separately by run_integrated_real.bat.
"""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from trl import Engine
from trl.retrieval import build_index, retrieve
from trl.message import Message, SYSTEM, HISTORY, USER_QUERY
from trl.util import count_tokens, load_config
import trl.compress as _C
import trl.util as _util

TOKENIZER = "tiktoken/cl100k" if _util._ENC is not None else "heuristic (~4 chars/tok)"

# Real questions about THIS repo, each targeting a real symbol so retrieval hits.
# (query, gold_symbol_name, gold_impl_file): the DEFINITION that actually answers
# the question -- not a test file that merely names the concept. Recall@k checks
# the real impl slice made the cut, so reduction% can't hide a wrong retrieval.
QUESTIONS = [
    ("how does compress_request fold and shrink the tail?", "compress_request", "trl/compress.py"),
    ("how does cascade decide to answer locally vs escalate?", "cascade", "trl/cascade.py"),
    ("how does _preserve_facts stop the compressor dropping numbers?", "_preserve_facts", "trl/compress.py"),
    ("what does stable_prefix mark for caching?", "stable_prefix", "trl/cache.py"),
    ("how does retrieve rank and budget the code slices?", "retrieve", "trl/retrieval/retrieve.py"),
    ("how does count_tokens fall back without tiktoken?", "count_tokens", "trl/util.py"),
]

_CACHE_RATE = 0.10   # cached input billed at ~10% of full (order-of-magnitude)


def _whole_repo(index):
    buf = []
    for fp in sorted(index.get("files", [])):
        try:
            buf.append(open(fp, encoding="utf-8", errors="replace").read())
        except Exception:
            pass
    return "\n".join(buf)


def run(steps=None):
    steps = steps or len(QUESTIONS)
    cfg = load_config("config.yaml")
    cfg.setdefault("local_model", {})["provider"] = "mock"   # local compressor stand-in
    eng = Engine(cfg)
    rcfg = cfg.get("retrieval", {})
    budget = int(rcfg.get("token_budget", 800)); k = int(rcfg.get("k", 8))

    index = build_index(".")
    repo = _whole_repo(index)
    repo_tok = count_tokens(repo)
    prefix = ("You are a coding agent for this repository. Follow the source "
              "exactly. Tools: read(path), grep(query), symbol(name).\n") * 12
    prefix_tok = count_tokens(prefix)

    cascade_on = eng.local.available()   # real (ollama) local model reachable?
    _C._clear_compress_cache()

    print(f"repo indexed: {len(index.get('files', []))} files, "
          f"{len(index['symbols'])} symbols, ~{repo_tok} tok dump")
    print(f"tokenizer: {TOKENIZER}   cascade: {'ON' if cascade_on else 'OFF (no local model reachable)'}")
    print(f"prefix ~{prefix_tok} tok  retrieval budget {budget}/k{k}\n")

    hdr = (f"{'step':>4} {'naive_in':>9} {'+retr':>8} {'+compr':>8} {'+cache':>8} "
           f"{'cut%':>6} {'fact':>5} {'gold@k':>7}")
    print(hdr)
    recall_hits = 0
    history = []
    fact_ok_all = True
    tot = {"naive": 0, "retr": 0, "compr": 0, "cache": 0}
    for i in range(steps):
        q, gold_name, gold_file = QUESTIONS[i % len(QUESTIONS)]
        hist_text = "\n".join(history)
        # a numeric fact enters the history each step -> must survive compression
        fact = 1000 + i * 111
        history.append(f"Q: {q}\nA: (resolved) checksum_{i} = {fact}")

        # ---- NAIVE: whole repo + full history + query, every step ----
        naive_in = prefix_tok + repo_tok + count_tokens(hist_text) + count_tokens(q)

        # ---- LEVER 1 retrieval: whole repo -> relevant slices ----
        r = retrieve(index, q, token_budget=budget, k=k)
        slice_tok = count_tokens(r["context"])
        gold_hit = any(sym.name == gold_name and gold_file in sym.file.replace("\\", "/")
                       for sym in r["symbols"])
        recall_hits += int(gold_hit)
        top_files = [sym.file.replace("\\", "/") for sym in r["symbols"][:3]]
        after_retr = prefix_tok + slice_tok + count_tokens(hist_text) + count_tokens(q)

        # ---- LEVER 2 compression: engine compresses the history tail ----
        msgs = [Message("system", SYSTEM, prefix)]
        if hist_text:
            msgs.append(Message("assistant", HISTORY, hist_text))
        msgs.append(Message("user", USER_QUERY, q))
        res = eng.process(msgs)
        comp_hist = "\n".join(m.content for m in res.messages
                              if m.kind == HISTORY)
        ch = count_tokens(comp_hist); qk = count_tokens(q)
        after_compr = prefix_tok + slice_tok + ch + qk

        # ---- LEVER 3 caching: settled prefix (system + compressed history) is
        # billed at the cache rate on repeat steps; slice + live query are fresh.
        settled = prefix_tok + ch            # == res.meta["cache_settled_tokens"]
        after_cache = _CACHE_RATE * settled + slice_tok + qk

        cut = 100 * (1 - after_cache / naive_in)
        # fact guard: the number from a PRIOR step must survive compression
        prior_fact = str(1000 + (i - 1) * 111) if i > 0 else str(fact)
        fact_ok = (i == 0) or (prior_fact in comp_hist)
        fact_ok_all = fact_ok_all and fact_ok

        print(f"{i:>4} {naive_in:>9,} {after_retr:>8,} {after_compr:>8,} "
              f"{after_cache:>8,.0f} {cut:>5.1f}% {'ok' if fact_ok else 'MISS':>5} "
              f"{('HIT' if gold_hit else 'MISS'):>7}")
        if not gold_hit:
            print(f"       ^ gold {gold_name} ({gold_file}) MISSED; top slices: {top_files}")
        tot["naive"] += naive_in; tot["retr"] += after_retr
        tot["compr"] += after_compr; tot["cache"] += after_cache

    def red(x):
        return 100 * (1 - tot[x] / tot["naive"])
    print("\n--- cumulative input-token reduction vs naive (levers stack) ---")
    print(f"  retrieval only          : {red('retr'):5.1f}%")
    print(f"  retrieval + compression : {red('compr'):5.1f}%")
    print(f"  + caching (billed)       : {red('cache'):5.1f}%")
    print(f"  fact-guard held every step: {fact_ok_all}")
    print(f"  retrieval recall@{k} (gold symbol in slices): {recall_hits}/{steps} "
          f"= {100*recall_hits/steps:.0f}%")
    print("DONE")
    return {"reduction_all": red("cache"), "fact_ok": fact_ok_all,
            "reduction_retr": red("retr"), "reduction_compr": red("compr"),
            "recall": recall_hits, "steps": steps}


if __name__ == "__main__":
    run()
