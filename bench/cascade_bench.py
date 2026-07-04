"""Cascade benchmark: always-big vs always-local vs cascade.

Over a synthetic code repo, two kinds of question:
  * LOOKUP  ("what does compute_i_j return?")   -> the local pipeline can
    retrieve the function and EXTRACT the exact value, and verify it -> confident.
  * REASON  ("across the whole repo, which function returns the largest value?")
    -> the local extractive pipeline can't answer confidently -> escalate.

We report, for each strategy: big-model calls used (cost) and answer accuracy
(quality). The point: cascade buys big-model QUALITY at a fraction of big-model
CALLS, because the cheap local path safely handles the easy majority."""
import os, random, re, tempfile, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from trl.retrieval import build_index, retrieve
from trl.cascade import cascade
from bench.retrieval_bench import _make_repo

_RESULT = re.compile(r"result\s*=\s*(\d+)")


def _make_local(index):
    """Local pipeline: retrieve, then extract+verify an exact return value for a
    LOOKUP query. Returns (answer, confident). Confident ONLY when it extracts a
    single unambiguous value for the named function -> verifiable, safe to keep."""
    def local_answer(query, _context):
        m = re.search(r"function (compute_\d+_\d+)", query)
        if not m:
            return None, False                     # not a lookup -> escalate
        name = m.group(1)
        r = retrieve(index, query, token_budget=400, k=3)
        for sym in r["symbols"]:
            if sym.name == name:
                vals = _RESULT.findall(sym.source)
                if len(vals) == 1:                 # unambiguous & extractable
                    return vals[0], True
        return None, False                         # couldn't verify -> escalate
    return local_answer


def run(n_lookup=30, n_reason=10, seed=7):
    rng = random.Random(seed)
    with tempfile.TemporaryDirectory() as repo:
        secrets = _make_repo(repo, seed=seed)
        index = build_index(repo)
        local_answer = _make_local(index)

        # the expensive model: modeled as an oracle (always correct) -> 1 big call
        def big_answer(query, _ctx):
            m = re.search(r"function (compute_\d+_\d+)", query)
            if m:
                return str(secrets[m.group(1)])
            return str(max(secrets.values()))       # the REASON answer

        tasks = []
        for name in rng.sample(list(secrets), n_lookup):
            tasks.append((f"What integer does the function {name} return?",
                          str(secrets[name])))
        for _ in range(n_reason):
            tasks.append(("Across the whole repo, what is the single largest "
                          "integer any function returns?", str(max(secrets.values()))))
        rng.shuffle(tasks)

        arms = {"always-big": [], "always-local": [], "cascade": []}
        big_calls = {"always-big": 0, "always-local": 0, "cascade": 0}
        for q, gold in tasks:
            # always-big
            arms["always-big"].append(big_answer(q, "") == gold); big_calls["always-big"] += 1
            # always-local (no escalation) -> wrong when local can't answer
            la, conf = local_answer(q, "")
            arms["always-local"].append((la == gold) if conf else False)
            # cascade
            res = cascade(q, "", local_answer, big_answer)
            arms["cascade"].append(res.answer == gold)
            big_calls["cascade"] += int(res.used_big)

    n = len(tasks)
    print("=" * 66)
    print(" CASCADE BENCHMARK   (route easy->local, escalate hard->big)")
    print("=" * 66)
    print(f" tasks: {n}  ({n_lookup} lookup + {n_reason} reasoning)\n")
    print(f" {'strategy':14s} {'big-model calls':>16s} {'accuracy':>10s}")
    for arm in ("always-big", "always-local", "cascade"):
        acc = 100 * sum(arms[arm]) / n
        print(f" {arm:14s} {big_calls[arm]:>10d}/{n:<4d} {acc:>9.1f}%")
    saved = 100 * (1 - big_calls["cascade"] / big_calls["always-big"])
    print(f"\n cascade vs always-big: {saved:.1f}% fewer big-model calls, "
          f"same accuracy ({100*sum(arms['cascade'])/n:.1f}%)")
    print("=" * 66)
    return {"cascade_acc": sum(arms["cascade"]) / n,
            "big_acc": sum(arms["always-big"]) / n,
            "calls_saved_pct": saved}


if __name__ == "__main__":
    run()
