"""Shared: resolve the user's project at RUNTIME and build-or-load a persistent,
incremental AST index for it.

Why runtime resolution: a Claude Code plugin MCP server's cwd is the PLUGIN root
(not the user's project), and ${...} interpolation inside a plugin's .mcp.json is
unreliable. So we never trust the manifest to pass the path -- we resolve it here.
"""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from trl.retrieval import build_index, save_index, load_index

INDEX_DIR = ".trl"
INDEX_NAME = "index.json"


def _git_root(start):
    """Nearest ancestor of `start` containing a .git dir, else None."""
    d = os.path.abspath(start)
    while True:
        if os.path.isdir(os.path.join(d, ".git")):
            return d
        parent = os.path.dirname(d)
        if parent == d:
            return None
        d = parent


def _resolve_repo(repo=None):
    """Resolve the target project dir at RUNTIME. Order:
    explicit arg -> $TRL_REPO -> $CLAUDE_PROJECT_DIR -> nearest .git above cwd -> cwd.
    Always returns a path."""
    if repo:
        return os.path.abspath(repo)
    for env in ("TRL_REPO", "CLAUDE_PROJECT_DIR"):
        v = os.environ.get(env)
        if v:
            return os.path.abspath(v)
    g = _git_root(os.getcwd())
    return g if g else os.getcwd()


def _has_explicit_repo(repo=None):
    """True only for a RELIABLE project signal (explicit arg or env). git-root/cwd are
    NOT reliable for a plugin MCP server, whose cwd is the plugin root -- callers that
    run there must gate on this to avoid indexing the wrong tree."""
    return bool(repo or os.environ.get("TRL_REPO") or os.environ.get("CLAUDE_PROJECT_DIR"))


def index_path(repo):
    return os.path.join(repo, INDEX_DIR, INDEX_NAME)


def get_index(repo=None):
    """Up-to-date index for the resolved repo, cached at <repo>/.trl/index.json so
    `/trl-index` and `retrieve_code` agree regardless of cwd. Incremental: only
    changed files are re-parsed."""
    repo = _resolve_repo(repo)
    cache = index_path(repo)
    prev = None
    if os.path.exists(cache):
        try:
            prev = load_index(cache)
        except Exception:
            prev = None
    idx = build_index(repo, prev=prev)
    try:
        os.makedirs(os.path.dirname(cache), exist_ok=True)
        save_index(idx, cache)
    except Exception:
        pass
    return idx
