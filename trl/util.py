"""Shared utilities: tokenizer-aware counting + config loading."""
import os
import re

# --- token counting --------------------------------------------------------
# Hard truth: cost is per TOKEN, not per character. Use a real tokenizer when
# available so compression that looks smaller in chars but tokenizes worse gets
# caught. Fall back to a ~4-chars/token heuristic offline.
_ENC = None
try:  # pragma: no cover - optional dep
    import tiktoken
    _ENC = tiktoken.get_encoding("cl100k_base")
except Exception:
    _ENC = None


def count_tokens(text: str) -> int:
    if not text:
        return 0
    if _ENC is not None:
        return len(_ENC.encode(text))
    # heuristic: whitespace-split words * ~1.3 subtokens, min chars/4
    words = len(text.split())
    return max(len(text) // 4, int(words * 1.3), 1)


# --- config ----------------------------------------------------------------
def load_config(path: str = "config.yaml") -> dict:
    try:
        import yaml
        with open(path, encoding="utf-8") as f:
            return yaml.safe_load(f) or {}   # empty file -> {} not None
    except ImportError:
        with open(path) as f:
            return _tiny_yaml(f.read())


def _tiny_yaml(text: str) -> dict:
    """Minimal YAML-subset parser: 2-space nesting, scalars, no lists.
    Enough for config.yaml so the mock path needs zero pip installs."""
    root: dict = {}
    stack = [(-1, root)]
    for raw in text.splitlines():
        line = raw.split("#", 1)[0].rstrip()
        if not line.strip():
            continue
        indent = len(line) - len(line.lstrip())
        key, _, val = line.strip().partition(":")
        val = val.strip()
        while stack and indent <= stack[-1][0]:
            stack.pop()
        parent = stack[-1][1]
        if val == "":
            node: dict = {}
            parent[key] = node
            stack.append((indent, node))
        else:
            parent[key] = _scalar(val)
    return root


def _scalar(v: str):
    if v.lower() in ("true", "false"):
        return v.lower() == "true"
    if re.fullmatch(r"-?\d+", v):
        return int(v)
    if re.fullmatch(r"-?\d*\.\d+", v):
        return float(v)
    return v.strip('"').strip("'")
