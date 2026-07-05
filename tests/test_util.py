"""trl/util.py — count_tokens, load_config, _tiny_yaml, _scalar.
Run: python tests/test_util.py"""
import os, sys, tempfile
import pytest
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import trl.util as util
from trl.util import count_tokens, load_config, _tiny_yaml, _scalar


# ---------------- count_tokens ----------------
def test_count_tokens_nonempty_positive():
    assert count_tokens("hello world, this is text") > 0
    assert count_tokens("x") >= 1


def test_count_tokens_empty_and_none_ish():
    assert count_tokens("") == 0
    # count_tokens(None) also hits the `if not text` guard
    assert count_tokens(None) == 0


def test_count_tokens_unicode():
    assert count_tokens("héllo wörld ünïcode") > 0
    assert count_tokens("日本語のテキストです") > 0
    assert count_tokens("emoji \U0001F600 test") > 0


def test_count_tokens_monotonic_on_repetition():
    t = "some words here "
    assert count_tokens(t * 10) > count_tokens(t)


def test_count_tokens_heuristic_formula(monkeypatch):
    # force the offline heuristic regardless of whether tiktoken is installed
    monkeypatch.setattr(util, "_ENC", None)
    text = "one two three four"          # 18 chars, 4 words
    assert count_tokens(text) == max(18 // 4, int(4 * 1.3), 1)
    assert count_tokens("a") == 1        # min clamp


# ---------------- load_config ----------------
def test_load_config_missing_file_returns_empty():
    # FIXED: a missing config file returns {} (sane default) instead of raising
    # FileNotFoundError (trl/util.py:load_config).
    assert load_config(os.path.join(tempfile.gettempdir(), "definitely_missing_trl.yaml")) == {}


def test_load_config_empty_file_gives_empty_dict(tmp_path):
    p = tmp_path / "empty.yaml"
    p.write_text("")
    assert load_config(str(p)) == {}


def test_load_config_roundtrip(tmp_path):
    p = tmp_path / "c.yaml"
    p.write_text("arms:\n  treatment:\n    native_prompt_cache: true\n"
                 "local_model:\n  provider: none\n")
    cfg = load_config(str(p))
    assert cfg["arms"]["treatment"]["native_prompt_cache"] is True
    assert cfg["local_model"]["provider"] == "none"


# ---------------- _tiny_yaml ----------------
def test_tiny_yaml_nesting_and_scalars():
    cfg = _tiny_yaml(
        "a: 1\n"
        "b:\n"
        "  c: true\n"
        "  d: -2.5\n"
        "  deep:\n"
        "    e: 'quoted'\n"
        "f: plain string\n")
    assert cfg == {"a": 1,
                   "b": {"c": True, "d": -2.5, "deep": {"e": "quoted"}},
                   "f": "plain string"}


def test_tiny_yaml_dedent_returns_to_parent():
    cfg = _tiny_yaml("a:\n  b: 1\nc: 2\n")
    assert cfg == {"a": {"b": 1}, "c": 2}


def test_tiny_yaml_comments_and_blank_lines():
    cfg = _tiny_yaml("# full comment\n\na: 5   # trailing comment\n\n")
    assert cfg == {"a": 5}


def test_tiny_yaml_empty_list_value_is_empty_list():
    # FIXED: `key: []` parses to an empty list, matching yaml.safe_load, so
    # `cfg["exts"] or default` behaves the same on the no-pyyaml path
    # (trl/util.py:_tiny_yaml/_scalar).
    cfg = _tiny_yaml("exts: []\n")
    assert cfg == {"exts": []}


def test_tiny_yaml_hash_inside_value_is_kept():
    # FIXED: '#' only starts a comment at line-start or after whitespace, so a
    # value containing '#' (e.g. a URL fragment) is preserved, matching real YAML
    # (trl/util.py:_tiny_yaml/_strip_comment).
    cfg = _tiny_yaml("url: http://host/page#frag\n")
    assert cfg == {"url": "http://host/page#frag"}


def test_tiny_yaml_negative_and_bool_scalars():
    assert _scalar("-7") == -7
    assert _scalar("-0.5") == -0.5
    assert _scalar("TRUE") is True
    assert _scalar("False") is False
    assert _scalar('"3"') == "3"          # quoted stays string... via strip
    assert _scalar("hello") == "hello"


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
