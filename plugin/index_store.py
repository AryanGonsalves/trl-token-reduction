"""Shared: build-or-load a persistent, incremental AST index for a repo."""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from trl.retrieval import build_index, save_index, load_index

CACHE_NAME = ".trl_index.json"


def get_index(repo: str):
    """Return an up-to-date index for `repo`, reusing/refreshing the on-disk cache
    incrementally (only changed files are re-parsed)."""
    repo = os.path.abspath(repo)
    cache = os.path.join(repo, CACHE_NAME)
    prev = None
    if os.path.exists(cache):
        try:
            prev = load_index(cache)
        except Exception:
            prev = None
    idx = build_index(repo, prev=prev)
    try:
        save_index(idx, cache)
    except Exception:
        pass
    return idx
