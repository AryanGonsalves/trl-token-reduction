"""Tree-sitter AST extractor (Python + JavaScript + TypeScript). Turns source
files into Symbols (functions, classes, methods, arrow-function consts) with
their exact source slice and the identifiers they reference (a cheap call graph
for 1-hop retrieval expansion). Local + deterministic: no model, no API tokens."""
from __future__ import annotations

import hashlib
import os
from dataclasses import dataclass, field
from typing import Dict, List, Set


def _py():   import tree_sitter_python as m; return m.language()
def _js():   import tree_sitter_javascript as m; return m.language()
def _ts():   import tree_sitter_typescript as m; return m.language_typescript()
def _tsx():  import tree_sitter_typescript as m; return m.language_tsx()
def _go():   import tree_sitter_go as m; return m.language()
def _rust(): import tree_sitter_rust as m; return m.language()
def _java(): import tree_sitter_java as m; return m.language()
def _cs():   import tree_sitter_c_sharp as m; return m.language()
def _c():    import tree_sitter_c as m; return m.language()
def _cpp():  import tree_sitter_cpp as m; return m.language()
def _ruby(): import tree_sitter_ruby as m; return m.language()
def _php():
    import tree_sitter_php as m
    fn = getattr(m, "language_php", None) or getattr(m, "language", None)
    return fn()
def _kt():   import tree_sitter_kotlin as m; return m.language()
def _luau(): import tree_sitter_luau as m; return m.language()

# per-language: grammar factory, {def-node: kind}, call-node type, arrow-consts?
_JS_DEFS = {"function_declaration": "function", "class_declaration": "class",
            "method_definition": "method"}
_LANGS = {
    ".py":  {"lang": _py,  "defs": {"function_definition": "function",
                                    "class_definition": "class"},
             "call": "call", "arrow": False},
    ".js":  {"lang": _js,  "defs": _JS_DEFS, "call": "call_expression", "arrow": True},
    ".jsx": {"lang": _js,  "defs": _JS_DEFS, "call": "call_expression", "arrow": True},
    ".mjs": {"lang": _js,  "defs": _JS_DEFS, "call": "call_expression", "arrow": True},
    ".ts":  {"lang": _ts,  "defs": _JS_DEFS, "call": "call_expression", "arrow": True},
    ".tsx": {"lang": _tsx, "defs": _JS_DEFS, "call": "call_expression", "arrow": True},
    ".go":  {"lang": _go, "defs": {"function_declaration": "function",
             "method_declaration": "method", "type_spec": "class"},
             "call": "call_expression", "arrow": False},
    ".rs":  {"lang": _rust, "defs": {"function_item": "function", "struct_item": "class",
             "enum_item": "class", "trait_item": "class"},
             "call": "call_expression", "arrow": False},
    ".java": {"lang": _java, "defs": {"class_declaration": "class",
              "method_declaration": "method", "interface_declaration": "class",
              "constructor_declaration": "method"},
              "call": "method_invocation", "arrow": False},
    ".cs":  {"lang": _cs, "defs": {"class_declaration": "class",
             "method_declaration": "method", "interface_declaration": "class",
             "struct_declaration": "class"},
             "call": "invocation_expression", "arrow": False},
    ".c":   {"lang": _c, "defs": {"function_definition": "function"},
             "call": "call_expression", "arrow": False},
    ".h":   {"lang": _c, "defs": {"function_definition": "function"},
             "call": "call_expression", "arrow": False},
    ".cpp": {"lang": _cpp, "defs": {"function_definition": "function",
             "class_specifier": "class", "struct_specifier": "class"},
             "call": "call_expression", "arrow": False},
    ".cc":  {"lang": _cpp, "defs": {"function_definition": "function",
             "class_specifier": "class", "struct_specifier": "class"},
             "call": "call_expression", "arrow": False},
    ".hpp": {"lang": _cpp, "defs": {"function_definition": "function",
             "class_specifier": "class", "struct_specifier": "class"},
             "call": "call_expression", "arrow": False},
    ".rb":  {"lang": _ruby, "defs": {"method": "function", "class": "class",
             "module": "class"}, "call": "call", "arrow": False},
    ".php": {"lang": _php, "defs": {"function_definition": "function",
             "method_declaration": "method", "class_declaration": "class",
             "interface_declaration": "class"},
             "call": "function_call_expression", "arrow": False},
    ".kt":  {"lang": _kt, "defs": {"function_declaration": "function",
             "class_declaration": "class", "object_declaration": "class"},
             "call": "call_expression", "arrow": False},
    ".luau": {"lang": _luau, "defs": {"function_declaration": "function"},
              "call": "function_call", "arrow": False},
    ".lua": {"lang": _luau, "defs": {"function_declaration": "function"},
             "call": "function_call", "arrow": False},
}

_IGNORE_DIRS = {
    ".git", "__pycache__", ".venv", "venv", "env", ".env", "build", "dist",
    "site-packages", "node_modules", ".tox", ".mypy_cache", ".pytest_cache",
    ".ruff_cache", "vendor", "third_party", ".idea", ".vscode", ".eggs",
    "__pypackages__", ".next", "out", "target", "bin", "obj",
}

_PARSERS: Dict[str, object] = {}

def _gitignore_specs(root: str):
    """Collect .gitignore specs from root down (git semantics: a .gitignore in a
    subdir applies to that subtree). Returns {dir_rel: PathSpec} or None if
    pathspec is unavailable. Matching walks the ancestor chain."""
    try:
        import pathspec
    except Exception:
        return None
    specs = {}
    for dp, dns, fns in os.walk(root):
        dns[:] = [d for d in dns if d not in _IGNORE_DIRS]
        if ".gitignore" in fns:
            try:
                with open(os.path.join(dp, ".gitignore"), encoding="utf-8", errors="replace") as f:
                    lines = f.read().splitlines()
                if lines:
                    rel = os.path.relpath(dp, root).replace(os.sep, "/")
                    specs[rel] = pathspec.PathSpec.from_lines("gitwildmatch", lines)
            except Exception:
                pass
    if not specs:
        return None

    def ignored(rel_path: str) -> bool:
        # check each ancestor dir's .gitignore against the path relative to it
        parts = rel_path.split("/")
        for i in range(len(parts)):
            base = "/".join(parts[:i]) or "."
            spec = specs.get(base)
            if spec is not None and spec.match_file("/".join(parts[i:])):
                return True
        return False
    return ignored



def _parser_for(ext: str):
    if ext not in _LANGS:
        return None
    if ext not in _PARSERS:
        try:
            from tree_sitter import Language, Parser
            lang = Language(_LANGS[ext]["lang"]())
            try:
                _PARSERS[ext] = Parser(lang)
            except Exception:
                pp = Parser(); pp.set_language(lang); _PARSERS[ext] = pp
        except Exception:
            _PARSERS[ext] = None     # grammar not installed -> skip these files
    return _PARSERS[ext]


@dataclass
class Symbol:
    name: str
    kind: str
    file: str
    start_line: int
    end_line: int
    source: str
    refs: Set[str] = field(default_factory=set)

    @property
    def id(self) -> str:
        return f"{self.file}:{self.name}:{self.start_line}"


def _text(node, src: bytes) -> str:
    return src[node.start_byte:node.end_byte].decode("utf-8", "replace")


_NAME_NODES = ("identifier", "field_identifier", "type_identifier",
               "constant", "simple_identifier", "name", "qualified_identifier")


def _def_name(node, src) -> str:
    nm = node.child_by_field_name("name")
    if nm is not None:
        return _text(nm, src).split("::")[-1].split(".")[-1].split(":")[-1]
    # C/C++: the name lives inside the declarator chain
    decl = node.child_by_field_name("declarator")
    seen = 0
    while decl is not None and seen < 6:
        seen += 1
        if decl.type in _NAME_NODES:
            return _text(decl, src).split("::")[-1]
        nxt = decl.child_by_field_name("declarator")
        if nxt is None:
            for c in decl.children:
                if c.type in _NAME_NODES:
                    return _text(c, src).split("::")[-1]
            break
        decl = nxt
    return "<anon>"


def _collect_refs(node, call_type, src, out):
    if node.type == call_type:
        fn = node.child_by_field_name("function") or node.child_by_field_name("name")
        if fn is not None:
            name = _text(fn, src).split(".")[-1].strip()
            if name.isidentifier():
                out.add(name)
    for c in node.children:
        _collect_refs(c, call_type, src, out)


def _mk(node, name, kind, path, src, call_type):
    refs: Set[str] = set()
    _collect_refs(node, call_type, src, refs)
    refs.discard(name)
    return Symbol(name=name, kind=kind, file=path,
                  start_line=node.start_point[0] + 1,
                  end_line=node.end_point[0] + 1,
                  source=_text(node, src), refs=refs)


def extract_file(path: str, source: bytes | None = None) -> List[Symbol]:
    ext = os.path.splitext(path)[1]
    spec = _LANGS.get(ext); parser = _parser_for(ext)
    if spec is None or parser is None:
        return []
    if source is None:
        with open(path, "rb") as f:
            source = f.read()
    tree = parser.parse(source)
    call_type = spec["call"]
    syms: List[Symbol] = []

    def visit(node, cls=None):
        handled = False
        if node.type in spec["defs"]:
            handled = True
            name = _def_name(node, source)
            base = spec["defs"][node.type]
            kind = "method" if (base == "function" and cls) else base
            syms.append(_mk(node, name, kind, path, source, call_type))
            new_cls = name if base == "class" else cls
            for c in node.children:
                visit(c, new_cls)
        # JS/TS: `const foo = (..) => {..}` / `= function(){}`  -> named function
        elif spec["arrow"] and node.type == "variable_declarator":
            val = node.child_by_field_name("value")
            nm = node.child_by_field_name("name")
            if val is not None and nm is not None and val.type in (
                    "arrow_function", "function_expression", "function"):
                handled = True
                syms.append(_mk(val, _text(nm, source),
                                "method" if cls else "function", path, source, call_type))
        if not handled:
            for c in node.children:
                visit(c, cls)

    visit(tree.root_node)
    return syms


def build_index(root: str, exts=tuple(_LANGS.keys()),
                prev: Dict | None = None) -> Dict[str, object]:
    """Walk `root` -> index. If `prev` (a prior index) is given, reuse its cached
    symbols for any file whose content hash is unchanged, and only re-parse the
    files that actually changed. Reports {reparsed:[...], reused:N} in _stats."""
    prev_files = (prev or {}).get("files", {})
    prev_syms: Dict[str, List[Symbol]] = {}
    for sym in (prev or {}).get("symbols", []):
        prev_syms.setdefault(sym.file, []).append(sym)

    symbols: List[Symbol] = []
    files: Dict[str, str] = {}
    reparsed: List[str] = []
    reused = 0
    root = os.path.abspath(root)
    ignored = _gitignore_specs(root)          # repo .gitignore matcher (or None)
    def _rel(path):
        return os.path.relpath(path, root).replace(os.sep, "/")
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames
                       if d not in _IGNORE_DIRS and not d.endswith(".egg-info")
                       and not (ignored and ignored(_rel(os.path.join(dirpath, d)) + "/"))]
        if "site-packages" in dirpath or os.sep + "build" + os.sep in dirpath:
            continue
        for fn in sorted(filenames):
            if os.path.splitext(fn)[1] not in exts:
                continue
            fp = os.path.join(dirpath, fn)
            if ignored and ignored(_rel(fp)):
                continue
            try:
                with open(fp, "rb") as f:
                    data = f.read()
            except Exception:
                continue
            h = hashlib.sha1(data).hexdigest()
            files[fp] = h
            if prev_files.get(fp) == h and fp in prev_syms:
                symbols.extend(prev_syms[fp]); reused += 1        # unchanged -> reuse
            else:
                symbols.extend(extract_file(fp, data)); reparsed.append(fp)
    return {"symbols": symbols, "files": files,
            "_stats": {"reparsed": reparsed, "reused": reused}}


def save_index(index: Dict, path: str) -> None:
    import json
    payload = {"files": index["files"],
               "symbols": [{"name": s.name, "kind": s.kind, "file": s.file,
                            "start_line": s.start_line, "end_line": s.end_line,
                            "source": s.source, "refs": sorted(s.refs)}
                           for s in index["symbols"]]}
    with open(path, "w", encoding="utf-8") as f:
        json.dump(payload, f)


def load_index(path: str) -> Dict:
    import json
    with open(path, encoding="utf-8") as f:
        d = json.load(f)
    syms = [Symbol(name=x["name"], kind=x["kind"], file=x["file"],
                   start_line=x["start_line"], end_line=x["end_line"],
                   source=x["source"], refs=set(x["refs"])) for x in d["symbols"]]
    # parity with build_index so callers can always read index["_stats"]
    return {"symbols": syms, "files": d["files"],
            "_stats": {"reparsed": [], "reused": len(syms)}}
