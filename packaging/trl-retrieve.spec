# -*- mode: python ; coding: utf-8 -*-
from PyInstaller.utils.hooks import collect_all, collect_submodules

datas, binaries, hiddenimports = [], [], []

_GRAMMARS = ["tree_sitter", "tree_sitter_python", "tree_sitter_javascript",
    "tree_sitter_typescript", "tree_sitter_go", "tree_sitter_rust", "tree_sitter_java",
    "tree_sitter_c_sharp", "tree_sitter_c", "tree_sitter_cpp", "tree_sitter_ruby",
    "tree_sitter_php", "tree_sitter_kotlin", "tree_sitter_luau"]

# tree-sitter grammars are imported dynamically inside functions, so PyInstaller can't
# see them; collect each package (module + compiled .pyd + data). mcp/pathspec/yaml too.
for pkg in _GRAMMARS + ["mcp", "pathspec", "yaml", "typer", "click"]:
    try:
        d, b, h = collect_all(pkg)
        datas += d; binaries += b; hiddenimports += h
    except Exception:
        pass

# our own packages live in the repo root
hiddenimports += collect_submodules("trl") + collect_submodules("plugin")

import os
ROOT = os.path.dirname(SPECPATH)
a = Analysis([os.path.join(SPECPATH, "frozen_server.py")], pathex=[ROOT], binaries=binaries,
             datas=datas, hiddenimports=hiddenimports,
             hookspath=[], runtime_hooks=[], excludes=["tiktoken"])
pyz = PYZ(a.pure)
exe = EXE(pyz, a.scripts, a.binaries, a.datas, [], name="trl-retrieve",
          debug=False, bootloader_ignore_signals=False, strip=False, upx=False,
          console=True)
