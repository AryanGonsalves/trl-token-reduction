"""Entry point for the PyInstaller-frozen TRL MCP retrieval server.
Runs the STDIO MCP server (like `python -m plugin.mcp_server`) but self-contained.
`--selftest` exercises the bundled grammars + retrieval and exits (proves the freeze works)."""
import os, sys
if hasattr(sys, "_MEIPASS"):
    sys.path.insert(0, sys._MEIPASS)


def _selftest():
    import tempfile
    from trl.retrieval.ast_index import build_index
    from trl.retrieval.retrieve import retrieve
    d = tempfile.mkdtemp()
    with open(os.path.join(d, "m.luau"), "w") as f:
        f.write("local Config = { GameName = 'X' }\nfunction Config.get() return 1 end\nreturn Config\n")
    with open(os.path.join(d, "s.py"), "w") as f:
        f.write("def hello():\n    return 1\n")
    idx = build_index(d)
    r = retrieve(idx, "config get", token_budget=200, k=3)
    langs = sorted({os.path.splitext(f)[1] for f in idx["files"]})
    print(f"SELFTEST OK: {len(idx['symbols'])} symbols, retrieved {len(r['symbols'])} "
          f"for 'config get', langs={langs}")


def main():
    if "--selftest" in sys.argv:
        _selftest()
        return
    from plugin.mcp_server import main as server_main
    server_main()


if __name__ == "__main__":
    main()
