"""Code-QA benchmark: AST retrieval vs whole-file dump.

Builds a synthetic repo, then for each task asks a question whose answer lives in
ONE function. Baseline stuffs the WHOLE repo into context; treatment sends only
the retrieved slice. We measure token reduction AND whether the answer-bearing
code survived (quality). Deterministic; no API needed."""
import os, random, tempfile, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from trl.retrieval import build_index, retrieve
from trl.util import count_tokens
from bench.stats import noninferiority


def _make_repo(root, n_files=8, fns_per_file=6, seed=7):
    rng = random.Random(seed)
    secrets = {}
    for fi in range(n_files):
        lines = ["import helpers\n"]
        for gi in range(fns_per_file):
            name = f"compute_{fi}_{gi}"
            secret = rng.randint(1000, 9999)
            secrets[name] = secret
            lines.append(
                f"def {name}(x):\n"
                f'    """Handles the {name} step of the pipeline."""\n'
                f"    tmp = x * 2 + 1\n"
                f"    for _ in range(3):\n"
                f"        tmp = (tmp + {rng.randint(1,9)}) % 100\n"
                f"    result = {secret}   # the load-bearing return value\n"
                f"    return result\n")
        with open(os.path.join(root, f"module_{fi}.py"), "w") as f:
            f.write("\n".join(lines))
    return secrets


def run(n_tasks=24, token_budget=600, seed=7):
    rng = random.Random(seed)
    with tempfile.TemporaryDirectory() as repo:
        secrets = _make_repo(repo, seed=seed)
        index = build_index(repo)
        whole = ""
        for fp in sorted(index["files"]):
            whole += open(fp).read() + "\n"
        base_tok = count_tokens(whole)

        targets = rng.sample(list(secrets), n_tasks)
        rows = []
        for name in targets:
            q = f"What integer does the function {name} return?"
            r = retrieve(index, q, token_budget=token_budget, k=6)
            ans = str(secrets[name])
            rows.append({"b_ok": int(ans in whole), "t_ok": int(ans in r["context"]),
                         "b_tok": base_tok, "t_tok": r["tokens"]})

    n = len(rows)
    b_tok = sum(r["b_tok"] for r in rows) / n
    t_tok = sum(r["t_tok"] for r in rows) / n
    ni = noninferiority([r["b_ok"] for r in rows], [r["t_ok"] for r in rows],
                        margin=0.01, seed=seed)
    print("=" * 64)
    print(" CODE-QA BENCHMARK  retrieval (AST slice) vs whole-file dump")
    print("=" * 64)
    print(f" tasks: {n}   repo: {len(secrets)} functions")
    print(f" context tokens/task:  {b_tok:.0f} (dump all) -> {t_tok:.0f} (retrieved)"
          f"   ({100*(1-t_tok/b_tok):.1f}% less, {b_tok/max(t_tok,1):.1f}x)")
    print(" quality (answer-bearing code present):")
    print(f"   baseline {ni['baseline_success']*100:.1f}%  ->  "
          f"retrieval {ni['treatment_success']*100:.1f}%   "
          f"non-inferior: {'PASS' if ni['non_inferior'] else 'FAIL'}")
    print("=" * 64)
    return ni


if __name__ == "__main__":
    run()
