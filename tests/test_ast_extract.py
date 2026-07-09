"""trl/retrieval/ast_index.py — extract_file (py/js), build_index walk,
content-hash incremental reuse, nested .gitignore, unknown ext, missing
grammar. Run: python tests/test_ast_extract.py"""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import trl.retrieval.ast_index as ai
from trl.retrieval.ast_index import build_index, extract_file

PY_SRC = b"""\
def helper(x):
    return x + 1

class Greeter:
    def greet(self, name):
        return helper(len(name))

def top():
    g = Greeter()
    return g.greet("hi")
"""

JS_SRC = b"""\
function loadUser(id) {
  return db.query(id);
}
const rateLimit = (n) => check(n);
class Api {
  fetchAll() { return loadUser(1); }
}
"""


def test_extract_python_symbols():
    syms = {s.name: s for s in extract_file("m.py", PY_SRC)}
    assert set(syms) == {"helper", "Greeter", "greet", "top"}
    assert syms["helper"].kind == "function"
    assert syms["Greeter"].kind == "class"
    assert syms["greet"].kind == "method"       # function inside class -> method
    assert syms["top"].kind == "function"
    # exact line ranges
    assert (syms["helper"].start_line, syms["helper"].end_line) == (1, 2)
    assert (syms["Greeter"].start_line, syms["Greeter"].end_line) == (4, 6)
    assert (syms["top"].start_line, syms["top"].end_line) == (8, 10)
    # refs = cheap call graph (own name excluded)
    assert "helper" in syms["greet"].refs
    assert "greet" in syms["top"].refs
    assert "helper" not in syms["helper"].refs
    # source is the exact slice
    assert syms["helper"].source == "def helper(x):\n    return x + 1"


def test_extract_javascript_symbols():
    syms = {s.name: s for s in extract_file("m.js", JS_SRC)}
    assert set(syms) >= {"loadUser", "rateLimit", "Api", "fetchAll"}
    assert syms["loadUser"].kind == "function"
    assert syms["rateLimit"].kind == "function"  # arrow-const -> named function
    assert syms["Api"].kind == "class"
    assert syms["fetchAll"].kind == "method"
    assert syms["loadUser"].start_line == 1 and syms["loadUser"].end_line == 3
    assert "loadUser" in syms["fetchAll"].refs
    assert "check" in syms["rateLimit"].refs


def test_unknown_extension_returns_empty_and_skipped(tmp_path):
    assert extract_file("notes.txt", b"def f():\n    pass\n") == []
    (tmp_path / "a.py").write_text("def real():\n    return 1\n")
    (tmp_path / "notes.txt").write_text("def fake():\n    pass\n")
    (tmp_path / "data.xyz").write_text("nothing")
    idx = build_index(str(tmp_path))
    assert {s.name for s in idx["symbols"]} == {"real"}
    assert all(f.endswith(".py") for f in idx["files"])


def test_build_index_walk_and_stats(tmp_path):
    (tmp_path / "pkg").mkdir()
    (tmp_path / "pkg" / "a.py").write_text("def fa():\n    return 1\n")
    (tmp_path / "b.py").write_text("def fb():\n    return 2\n")
    idx = build_index(str(tmp_path))
    assert {s.name for s in idx["symbols"]} == {"fa", "fb"}
    assert len(idx["files"]) == 2
    assert idx["_stats"]["reused"] == 0
    assert len(idx["_stats"]["reparsed"]) == 2


def test_incremental_rewrite_same_content_reuses(tmp_path):
    # content-hash based: rewriting a file with IDENTICAL bytes (new mtime)
    # must still reuse the cached symbols, not re-parse.
    p = tmp_path / "a.py"
    p.write_text("def same():\n    return 1\n")
    idx1 = build_index(str(tmp_path))
    p.write_text("def same():\n    return 1\n")   # touch, same bytes
    idx2 = build_index(str(tmp_path), prev=idx1)
    assert idx2["_stats"]["reused"] == 1
    assert idx2["_stats"]["reparsed"] == []
    assert {s.name for s in idx2["symbols"]} == {"same"}


def test_incremental_changed_file_reparsed(tmp_path):
    a, b = tmp_path / "a.py", tmp_path / "b.py"
    a.write_text("def fa():\n    return 1\n")
    b.write_text("def fb():\n    return 2\n")
    idx1 = build_index(str(tmp_path))
    b.write_text("def fb2():\n    return 999\n")
    idx2 = build_index(str(tmp_path), prev=idx1)
    assert idx2["_stats"]["reused"] == 1
    assert [os.path.basename(x) for x in idx2["_stats"]["reparsed"]] == ["b.py"]
    names = {s.name for s in idx2["symbols"]}
    assert names == {"fa", "fb2"}


def test_nested_gitignore_scopes_to_subtree(tmp_path):
    # a .gitignore in a subdir applies to that subtree only (git semantics)
    sub = tmp_path / "sub"
    sub.mkdir()
    (sub / ".gitignore").write_text("secret_*.py\n")
    (sub / "secret_x.py").write_text("def hidden():\n    return 1\n")
    (sub / "open.py").write_text("def visible():\n    return 2\n")
    # same pattern at root level is NOT excluded (only sub/'s spec has it)
    (tmp_path / "secret_root.py").write_text("def root_secret():\n    return 3\n")
    names = {s.name for s in build_index(str(tmp_path))["symbols"]}
    assert "hidden" not in names
    assert {"visible", "root_secret"} <= names


def test_gitignore_specs_none_without_gitignore(tmp_path):
    (tmp_path / "a.py").write_text("def f():\n    return 1\n")
    assert ai._gitignore_specs(str(tmp_path)) is None


def test_missing_grammar_skipped_gracefully(tmp_path):
    # simulate a language whose tree-sitter grammar isn't installed: the
    # parser factory raises -> extract_file returns [] and build_index walks on.
    def _broken():
        raise ImportError("grammar not installed")
    fake = dict(ai._LANGS[".py"])
    fake["lang"] = _broken
    ai._LANGS[".zqz"] = fake
    try:
        assert extract_file("x.zqz", b"def f():\n    pass\n") == []
        (tmp_path / "x.zqz").write_text("def f():\n    pass\n")
        (tmp_path / "ok.py").write_text("def ok():\n    return 1\n")
        idx = build_index(str(tmp_path), exts=(".py", ".zqz"))
        assert {s.name for s in idx["symbols"]} == {"ok"}
    finally:
        ai._LANGS.pop(".zqz", None)
        ai._PARSERS.pop(".zqz", None)


def test_symbol_id_unique_per_location():
    syms = extract_file("m.py", PY_SRC)
    ids = [s.id for s in syms]
    assert len(ids) == len(set(ids))
    assert all(s.id == f"{s.file}:{s.name}:{s.start_line}" for s in syms)


if __name__ == "__main__":
    import pytest
    raise SystemExit(pytest.main([__file__, "-q"]))


def test_luau_roblox_symbols(tmp_path):
    """Roblox Luau: table.method, table:method, and local function all extract with
    their last-segment name (Weapon.new -> new, Weapon:fire -> fire)."""
    from trl.retrieval.ast_index import extract_file
    f = tmp_path / "weapon.luau"
    f.write_text(
        "local Weapon = {}\n"
        "function Weapon.new(name) return setmetatable({ammo=30}, Weapon) end\n"
        "function Weapon:fire() self.ammo -= 1; hitscan(self) end\n"
        "local function reload(g) g.ammo = 30 end\n"
    )
    syms = {s.name: s for s in extract_file(str(f))}
    assert {"new", "fire", "reload"} <= set(syms), syms.keys()
    assert syms["new"].kind == "function"
    assert "setmetatable" in syms["new"].refs
    assert "hitscan" in syms["fire"].refs


def test_luau_module_tables_and_bootstrap(tmp_path):
    """Roblox reality: config tables, ModuleScript tables, and top-level bootstrap scripts
    must be indexed (not just functions), or structural queries return nothing."""
    from trl.retrieval.ast_index import extract_file
    cfg = tmp_path / "Config.luau"
    cfg.write_text("--!strict\nlocal Config = { GameName = \"Hoard!\" }\nreturn Config\n")
    c = {s.name: s for s in extract_file(str(cfg))}
    assert "Config" in c and c["Config"].kind == "table"

    svc = tmp_path / "DataService.luau"
    svc.write_text("local DataService = {}\nfunction DataService.Load(p) return {} end\n"
                   "return DataService\n")
    d = {s.name: s for s in extract_file(str(svc))}
    assert "DataService" in d and d["DataService"].kind == "table"
    assert "Load" in d  # functions still extracted alongside the table

    boot = tmp_path / "init.server.luau"
    boot.write_text("local X = require(script.DataService)\n"
                    "game.Players.PlayerAdded:Connect(function(p) end)\nprint(\"up\")\n")
    b = {s.name: s for s in extract_file(str(boot))}
    assert "init.server" in b and b["init.server"].kind == "module"
