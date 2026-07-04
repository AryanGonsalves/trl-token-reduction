"""MCP server exposing the retrieval engine to Claude Code (or any MCP client).
Configure a repo via env TRL_REPO (defaults to cwd). Tools:
  retrieve_code(query)   -> relevant slices instead of whole files
  explain_symbol(name)   -> exact source of a named function/class/method
"""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from plugin.index_store import get_index
from trl.retrieval import retrieve

try:
    from mcp.server.fastmcp import FastMCP
except Exception:
    FastMCP = None

_REPO = os.environ.get("TRL_REPO", os.getcwd())


def _idx():
    return get_index(_REPO)


if FastMCP is not None:
    mcp = FastMCP("trl-retrieve")

    @mcp.tool()
    def retrieve_code(query: str, budget: int = 1200) -> str:
        """Return the most relevant code slices for a question. Prefer this over
        grepping and reading whole files -- it returns exact source, far fewer tokens."""
        r = retrieve(_idx(), query, token_budget=budget, k=8)
        return r["context"] or "(no relevant symbols found)"

    @mcp.tool()
    def explain_symbol(name: str) -> str:
        """Return the exact source of a function/class/method by name."""
        idx = _idx()
        hits = [s for s in idx["symbols"] if s.name == name]
        if not hits:
            return f"(no symbol named {name})"
        return "\n\n".join(f"# {s.file}:{s.start_line}-{s.end_line} ({s.kind})\n{s.source}"
                           for s in hits[:5])

    def main():
        mcp.run()
else:
    def main():
        print("install the MCP SDK:  pip install mcp", file=sys.stderr); sys.exit(1)


if __name__ == "__main__":
    main()
