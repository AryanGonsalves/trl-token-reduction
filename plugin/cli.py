"""Bash-callable retrieval for Claude Code (and for humans).

  python -m plugin.cli "how does auth work?" [--repo DIR] [--budget 1200] [--k 8]

Prints only the relevant code slices (file:line + source) -- a drop-in for
`grep -r` + reading whole files, at a fraction of the tokens."""
import argparse, os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from plugin.index_store import get_index
from trl.retrieval import retrieve
from trl.util import count_tokens


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("query")
    ap.add_argument("--repo", default=None)   # None -> resolve $TRL_REPO/$CLAUDE_PROJECT_DIR/git-root/cwd
    ap.add_argument("--budget", type=int, default=1200)
    ap.add_argument("--k", type=int, default=8)
    a = ap.parse_args()
    idx = get_index(a.repo)   # index_store resolves + caches at <repo>/.trl/index.json
    r = retrieve(idx, a.query, token_budget=a.budget, k=a.k)
    if not r["symbols"]:
        print("(no relevant symbols found)"); return
    hdr = (f"# {len(r['symbols'])} slices, {r['tokens']} tokens "
           f"(indexed {len(idx['files'])} files, {len(idx['symbols'])} symbols)")
    print(hdr); print(r["context"])


if __name__ == "__main__":
    main()
