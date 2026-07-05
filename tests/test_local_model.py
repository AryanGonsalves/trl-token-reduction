"""trl/local_model.py — heuristic/smart compress, available(), summarize
fallbacks. No network: ollama/openai paths are monkeypatched.
Run: python tests/test_local_model.py"""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from trl.local_model import (LocalModel, heuristic_compress, smart_compress,
                             _is_boilerplate)


# ---------------- heuristic_compress ----------------
def test_heuristic_dedupes_exact_lines():
    text = "keep me once\nkeep me once\nkeep me once\nand this too"
    out = heuristic_compress(text)
    assert out == "keep me once\nand this too"


def test_heuristic_strips_boilerplate():
    text = ("real content line\n"
            "DEBUG something noisy\n"
            "TRACE more noise\n"
            "INFO: startup ok\n"
            "Traceback (most recent call last):\n"
            "at java.lang.Thread.run\n"
            "another real line")
    out = heuristic_compress(text)
    assert out == "real content line\nanother real line"


def test_heuristic_traceback_file_lines_stripped():
    # FIXED: the boilerplate marker is now 'File "' (no leading spaces) so python
    # traceback `File "..."` frames match after the line is stripped and are
    # removed (trl/local_model.py:heuristic_compress / _BOILERPLATE).
    text = "real line\n  File \"x.py\", line 3, in f\nother line"
    out = heuristic_compress(text)
    assert 'File "x.py"' not in out
    assert out == "real line\nother line"


def test_heuristic_keeps_unique_information():
    lines = [f"unique fact {i}" for i in range(10)]
    assert heuristic_compress("\n".join(lines)) == "\n".join(lines)


def test_heuristic_drops_blank_lines_and_never_expands():
    text = "a\n\n\nb\n\n"
    out = heuristic_compress(text)
    assert out == "a\nb"
    assert len(out) <= len(text)


def test_is_boilerplate_prefixes():
    assert _is_boilerplate("DEBUG x")
    assert _is_boilerplate("at foo.bar(Baz.java:1)")
    assert not _is_boilerplate("DEBUGGERS ARE GREAT"[:0] + "debug lowercase not matched")


# ---------------- smart_compress ----------------
def test_smart_keeps_first_line_and_facts():
    text = ("Report intro line with no digits\n"
            "pure narrative goes away\n"
            "KEYFACT: refund approved\n"
            "order 4471 flagged\n"
            "closing pleasantries")
    out = smart_compress(text).splitlines()
    assert out[0] == "Report intro line with no digits"   # structure kept
    assert "KEYFACT: refund approved" in out
    assert "order 4471 flagged" in out
    assert "pure narrative goes away" not in out
    assert "closing pleasantries" not in out


def test_smart_dedupes_kept_lines():
    text = "intro 1\nSTATUS: ok\nSTATUS: ok\nSTATUS: ok"
    out = smart_compress(text)
    assert out.count("STATUS: ok") == 1


# ---------------- available() ----------------
def test_available_false_when_provider_not_ollama():
    for p in ("none", "mock", "openai", ""):
        assert LocalModel({"provider": p}).available() is False, p


def test_available_false_when_endpoint_down(monkeypatch):
    import trl.local_model as lm_mod
    def boom(*a, **kw):
        raise OSError("no network in tests")
    monkeypatch.setattr(lm_mod.urllib.request, "urlopen", boom)
    lm = LocalModel({"provider": "ollama", "model": "m"})
    assert lm.available() is False


# ---------------- summarize fallbacks ----------------
def test_summarize_provider_none_uses_heuristic():
    lm = LocalModel({"provider": "none"})
    text = "dup\ndup\nfact 42"
    out = lm.summarize(text, "compress")
    assert out == "dup\nfact 42"
    assert len(out) <= len(text)


def test_summarize_provider_mock_uses_smart():
    lm = LocalModel({"provider": "mock"})
    text = "intro\nnarrative filler words\norder 99"
    assert lm.summarize(text, "i") == smart_compress(text)


def test_summarize_ollama_error_falls_back(monkeypatch):
    lm = LocalModel({"provider": "ollama", "model": "m"})
    monkeypatch.setattr(LocalModel, "available", lambda self: True)
    def boom(self, text, instruction):
        raise RuntimeError("model exploded")
    monkeypatch.setattr(LocalModel, "_ollama", boom)
    text = "dup\ndup\nkeep 7"
    assert lm.summarize(text, "i") == heuristic_compress(text)


def test_summarize_ollama_expansion_rejected(monkeypatch):
    # a local model that EXPANDS the text must be ignored (never make it worse)
    lm = LocalModel({"provider": "ollama", "model": "m"})
    monkeypatch.setattr(LocalModel, "available", lambda self: True)
    monkeypatch.setattr(LocalModel, "_ollama",
                        lambda self, t, i: t + t + "extra padding")
    text = "dup\ndup\nkeep 7"
    assert lm.summarize(text, "i") == heuristic_compress(text)


def test_summarize_ollama_empty_rejected(monkeypatch):
    lm = LocalModel({"provider": "ollama", "model": "m"})
    monkeypatch.setattr(LocalModel, "available", lambda self: True)
    monkeypatch.setattr(LocalModel, "_ollama", lambda self, t, i: "")
    text = "dup\ndup\nkeep 7"
    assert lm.summarize(text, "i") == heuristic_compress(text)


def test_summarize_ollama_good_output_used(monkeypatch):
    lm = LocalModel({"provider": "ollama", "model": "m"})
    monkeypatch.setattr(LocalModel, "available", lambda self: True)
    monkeypatch.setattr(LocalModel, "_ollama", lambda self, t, i: "tiny")
    assert lm.summarize("a much longer original text", "i") == "tiny"


def test_summarize_openai_error_falls_back(monkeypatch):
    lm = LocalModel({"provider": "openai", "model": "gpt-4o-mini"})
    def boom(self, text, instruction):
        raise RuntimeError("no api key / no network")
    monkeypatch.setattr(LocalModel, "_openai", boom)
    text = "dup\ndup\nkeep 7"
    assert lm.summarize(text, "i") == heuristic_compress(text)


def test_summarize_never_blanks_on_all_boilerplate():
    # FIXED: summarize honors its "never blank out" contract. When every line is
    # boilerplate (heuristic_compress -> ""), it returns the original text rather
    # than an empty payload (trl/local_model.py:LocalModel.summarize).
    lm = LocalModel({"provider": "none"})
    src = "DEBUG a\nTRACE b\nINFO: c"
    out = lm.summarize(src, "i")
    assert out.strip() != ""
    assert out == src


if __name__ == "__main__":
    import pytest
    raise SystemExit(pytest.main([__file__, "-q"]))
