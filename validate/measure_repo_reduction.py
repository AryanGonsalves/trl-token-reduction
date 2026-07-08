"""Measure TRL retrieval token-reduction on ANY repo — point it at your own code.

  python -m validate.measure_repo_reduction --repo /path/to/repo [--budget 1500 --k 8]
  python -m validate.measure_repo_reduction --repo . --queries "where is auth handled"

Per query: retrieved-slice tokens vs the whole-repo dump, and the reduction %.
Pure local retrieval + tiktoken counting — no network, no API keys."""
import argparse, os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from trl.retrieval.ast_index import build_index
from trl.retrieval.retrieve import retrieve
from trl.util import count_tokens

DEFAULT_Q = [
    "where are credentials or api keys loaded and used",
    "how is the main configuration loaded and parsed",
    "where are subprocess or shell commands executed",
    "how are errors and exceptions handled and logged",
]

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--repo", default=".")
    ap.add_argument("--budget", type=int, default=1500)
    ap.add_argument("--k", type=int, default=8)
    ap.add_argument("--queries", nargs="*", default=None)
    a = ap.parse_args()
    idx = build_index(a.repo)
    files = idx["files"]
    dump = sum(count_tokens(open(f, encoding="utf-8", errors="ignore").read()) for f in files)
    qs = a.queries or DEFAULT_Q
    print(f"repo {a.repo}: {len(files)} files, {len(idx['symbols'])} symbols, "
          f"{dump:,} tokens (whole-dump baseline)\n")
    print(f"{'query':54}{'slice tok':>10}{'vs dump':>9}  top slice")
    tot = 0
    for q in qs:
        r = retrieve(idx, q, token_budget=a.budget, k=a.k)
        t = r["tokens"]; tot += t
        top = r["symbols"][0] if r["symbols"] else None
        tn = f"{os.path.basename(top.file)}:{top.name}" if top else "(none)"
        vd = 100 * (1 - t / dump) if dump else 0
        print(f"{q[:54]:54}{t:>10}{vd:>8.1f}%  {tn}")
    print(f"\navg reduction vs whole-dump: {100*(1-tot/(dump*len(qs))):.1f}%  over {len(qs)} queries")

if __name__ == "__main__":
    main()
