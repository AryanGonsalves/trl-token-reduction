"""Compound pipeline benchmark: all four levers stacked on ONE code-agent session.

A coding agent answers T questions over a repo. Each turn it (naively) re-sends
the whole repo + the growing conversation history to the big model.

  NAIVE baseline (what agents do today):
    every turn -> [system+tools prefix] + [WHOLE repo dump] + [full history] -> BIG model

  PIPELINE (our layer):
    retrieval  -> only the relevant AST slices instead of the whole repo
    caching    -> the stable prefix billed once at the cache rate, not full, each turn
    compression-> the growing history compressed (+ fact guard) before re-send
    cascade    -> verifiable lookup turns answered LOCALLY ($0, no big call at all)

We report big-model input tokens, big-model calls, and $ -- naive vs pipeline --
at equal answer quality. The point: the levers MULTIPLY."""
import os, random, re, tempfile, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from trl.retrieval import build_index, retrieve
from trl.cascade import cascade
from trl.compress import compress_request
from trl.local_model import LocalModel
from trl.message import Message, HISTORY
from trl.util import count_tokens, load_config
from bench.retrieval_bench import _make_repo

_RESULT = re.compile(r"result\s*=\s*(\d+)")


def run(turns=20, seed=7):
    rng = random.Random(seed)
    cfg = load_config("config.yaml")
    price = cfg["big_model"]
    p_in = price["price_in_per_mtok"]; p_cache = price["price_cached_in_per_mtok"]
    p_out = price["price_out_per_mtok"]
    local = LocalModel({"provider": "mock"})   # smart_compress stand-in + guard

    with tempfile.TemporaryDirectory() as repo:
        secrets = _make_repo(repo, seed=seed)
        index = build_index(repo)
        whole_repo = ""
        for fp in sorted(index["files"]):
            whole_repo += open(fp).read() + "\n"
        prefix = ("You are a coding agent. Follow the source exactly. " * 40 +
                  "\ntools: read(path), grep(q), sum(field)\n" * 20)
        prefix_tok = count_tokens(prefix)

        # build a session: mostly verifiable lookups + a few reasoning turns
        turns_list = []
        names = rng.sample(list(secrets), turns)
        for i, name in enumerate(names):
            if i % 5 == 4:      # ~20% reasoning
                turns_list.append(("Across the whole repo, what is the single "
                                   "largest integer any function returns?",
                                   str(max(secrets.values())), "reason"))
            else:
                turns_list.append((f"What integer does {name} return?",
                                   str(secrets[name]), "lookup"))

        def big(query, ctx):    # oracle big model (always correct); ~40 output tok
            m = re.search(r"(compute_\d+_\d+)", query)
            return str(secrets[m.group(1)]) if m else str(max(secrets.values()))

        def local_answer(query, ctx):
            m = re.search(r"(compute_\d+_\d+)", query)
            if not m:
                return None, False
            r = retrieve(index, query, token_budget=400, k=3)
            for s in r["symbols"]:
                if s.name == m.group(1):
                    v = _RESULT.findall(s.source)
                    if len(v) == 1:
                        return v[0], True
            return None, False

        # ---- run both strategies ----
        naive_in = naive_cached = naive_out = 0; naive_calls = 0; naive_ok = 0
        pipe_in = pipe_cached = pipe_out = 0; pipe_calls = 0; pipe_ok = 0
        history = []   # list of prior "Q -> A" strings (the growing tail)

        for query, gold, kind in turns_list:
            hist_text = "\n".join(history)
            # ---------- NAIVE ----------
            naive_cached += prefix_tok                       # prefix re-sent (no cache)
            naive_in += count_tokens(whole_repo) + count_tokens(hist_text)
            naive_out += 40; naive_calls += 1
            naive_ok += (big(query, "") == gold)
            # ---------- PIPELINE ----------
            # cascade first: verifiable lookup -> LOCAL, no big call, ~0 big tokens
            res = cascade(query, "", local_answer, big)
            pipe_ok += (res.answer == gold)
            if not res.used_big:
                pass   # handled locally: zero big-model tokens/calls this turn
            else:
                # escalate: retrieval slice (not whole repo) + compressed history
                r = retrieve(index, query, token_budget=800, k=6)
                hist_msgs = [Message("assistant", HISTORY, hist_text)] if hist_text else []
                comp, _ = compress_request(hist_msgs, "safe", local) if hist_msgs else ([], 0)
                comp_hist = comp[0].content if comp else ""
                pipe_cached += prefix_tok                    # prefix billed at cache rate
                pipe_in += count_tokens(r["context"]) + count_tokens(comp_hist)
                pipe_out += 40; pipe_calls += 1
            history.append(f"Q: {query}\nA: {gold}")

    def cost(full_in, cached_in, out):
        return (full_in * p_in + cached_in * p_cache + out * p_out) / 1e6

    n = len(turns_list)
    naive_cost = cost(naive_in, naive_cached, naive_out)
    pipe_cost = cost(pipe_in, pipe_cached, pipe_out)
    print("=" * 70)
    print(" COMPOUND PIPELINE   all 4 levers on one %d-turn code-agent session" % n)
    print("=" * 70)
    print(f" {'':22s}{'NAIVE':>14s}{'PIPELINE':>14s}")
    print(f" big-model calls      {naive_calls:>14d}{pipe_calls:>14d}   (cascade)")
    print(f" big-model in-tokens  {naive_in:>14,d}{pipe_in:>14,d}   (retrieval+compress)")
    print(f" cache-rate tokens    {naive_cached:>14,d}{pipe_cached:>14,d}   (caching)")
    print(f" API cost $           {naive_cost:>14.4f}{pipe_cost:>14.4f}")
    print(f" answer accuracy      {100*naive_ok/n:>13.1f}%{100*pipe_ok/n:>13.1f}%")
    print("-" * 70)
    print(f" COMPOUND: {naive_cost/pipe_cost:.1f}x cheaper "
          f"({100*(1-pipe_cost/naive_cost):.1f}% less $), "
          f"{100*(1-pipe_calls/naive_calls):.0f}% fewer big calls, "
          f"quality {100*pipe_ok/n:.0f}%={'=' if pipe_ok==naive_ok else '!='}=naive")
    print("=" * 70)
    return {"mult": naive_cost / pipe_cost, "pipe_ok": pipe_ok, "naive_ok": naive_ok}


if __name__ == "__main__":
    run()
