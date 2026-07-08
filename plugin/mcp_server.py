"""MCP server exposing the retrieval engine to Claude Code (or any MCP client).

The target project is resolved AT RUNTIME (see plugin.index_store._resolve_repo):
$TRL_REPO -> $CLAUDE_PROJECT_DIR -> nearest .git above cwd -> cwd. We do NOT rely on
manifest ${...} interpolation. Because an MCP server's cwd is the PLUGIN root, if no
reliable signal is present the tools return a "run /trl-index or set TRL_REPO" hint
instead of silently indexing the plugin's own tree. Both tools accept repo= override.

Tools:
  retrieve_code(query, repo=?)   -> relevant slices instead of whole files
  explain_symbol(name, repo=?)   -> exact source of a named function/class/method
"""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from plugin.index_store import get_index, _resolve_repo, _has_explicit_repo
from trl.retrieval import retrieve

try:
    from mcp.server.fastmcp import FastMCP
except Exception:
    FastMCP = None

_PLUGIN_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_UNRESOLVED = ("TRL: couldn't resolve your project -- this MCP server runs from the "
               "plugin directory. Run /trl-index in your project, set TRL_REPO, or "
               "call this tool with repo='/path/to/your/project'.")


def _target(repo=None):
    """Resolved project path, or None if we can't CONFIDENTLY resolve it (no explicit
    arg/env and resolution falls back to the plugin root)."""
    if _has_explicit_repo(repo):
        return _resolve_repo(repo)
    resolved = _resolve_repo(repo)
    if os.path.abspath(resolved) == _PLUGIN_ROOT:
        return None
    return resolved


def _log_savings(kind, query, target, slice_tokens, symbols):
    """Best-effort adoption + savings log (opt-in via env TRL_SAVINGS_LOG). Records the
    slices actually returned vs the whole-file counterfactual (the files those slices came
    from), so cumulative savings sum across sessions. NEVER raises -- must not break retrieval."""
    path = os.environ.get("TRL_SAVINGS_LOG")
    if not path:
        return
    try:
        import json, time
        from trl.util import count_tokens
        files = {s.file for s in symbols}
        whole = 0
        for f in files:
            try:
                whole += count_tokens(open(f, encoding="utf-8", errors="ignore").read())
            except Exception:
                pass
        rec = {"ts": time.time(), "tool": kind, "repo": target, "query": (query or "")[:120],
               "slice_tokens": int(slice_tokens), "wholefile_tokens": whole,
               "saved": max(0, whole - int(slice_tokens)), "n_slices": len(symbols),
               "n_files": len(files)}
        os.makedirs(os.path.dirname(os.path.abspath(path)) or ".", exist_ok=True)
        with open(path, "a", encoding="utf-8") as fh:
            fh.write(json.dumps(rec) + "\n")
    except Exception:
        pass


if FastMCP is not None:
    mcp = FastMCP("trl-retrieve")

    @mcp.tool()
    def retrieve_code(query: str, budget: int = 1200, repo: str = "") -> str:
        """Return the most relevant code slices for a question. Prefer this over
        grepping and reading whole files -- exact source, far fewer tokens. Pass
        repo='/path' to target a specific project."""
        target = _target(repo or None)
        if target is None:
            return _UNRESOLVED
        r = retrieve(get_index(target), query, token_budget=budget, k=8)
        _log_savings("retrieve_code", query, target, r["tokens"], r["symbols"])
        return r["context"] or "(no relevant symbols found)"

    @mcp.tool()
    def explain_symbol(name: str, repo: str = "") -> str:
        """Return the exact source of a function/class/method by name. Pass
        repo='/path' to target a specific project."""
        target = _target(repo or None)
        if target is None:
            return _UNRESOLVED
        idx = get_index(target)
        hits = [s for s in idx["symbols"] if s.name == name]
        if not hits:
            return f"(no symbol named {name})"
        picked = hits[:5]
        from trl.util import count_tokens
        _log_savings("explain_symbol", name, target, sum(count_tokens(s.source) for s in picked), picked)
        return "\n\n".join(f"# {s.file}:{s.start_line}-{s.end_line} ({s.kind})\n{s.source}"
                           for s in picked)

    def main():
        mcp.run()
else:
    def main():
        print("install the MCP SDK:  pip install mcp", file=sys.stderr); sys.exit(1)


if __name__ == "__main__":
    main()
