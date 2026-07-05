"""trl/retrieval/retrieve.py — _tokens/_score, 1-hop call-graph expansion,
token budget, k, rerank=False determinism, empty query.
Run: python tests/test_retrieve_unit.py"""
import os, sys, tempfile
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from trl.retrieval import build_index, retrieve
from trl.retrieval.ast_index import extract_file
from trl.retrieval.retrieve import _tokens, _score, _cos


def _mkindex(files: dict):
    d = tempfile.mkdtemp()
    for name, src in files.items():
        with open(os.path.join(d, name), "w") as f:
            f.write(src)
    return build_index(d)


def test_tokens_splits_camel_and_snake():
    t = _tokens("rateLimitCheck do_the_thing x")
    # full identifiers, lowercased
    assert "ratelimitcheck" in t and "do_the_thing" in t
    # camelCase + snake_case parts of length >= 3
    assert {"rate", "limit", "check", "the", "thing"} <= t
    # short fragments (<3 chars) excluded as parts, but whole short ids kept
    assert "do" not in t and "x" in t


def test_score_weights_name_over_refs():
    syms = extract_file("m.py", b"def rate_limit(n):\n    return check(n)\n\n"
                                b"def other():\n    return rate_limit(1)\n")
    by = {s.name: s for s in syms}
    q = _tokens("rate limit")
    # name hit (5.0/term) must dominate a mere ref hit (1.0/term)
    assert _score(by["rate_limit"], q) > _score(by["other"], q)
    assert _score(by["other"], q) > 0          # refs still count a bit


def test_score_zero_for_unrelated():
    syms = extract_file("m.py", b"def compute_tax(a):\n    return a * 2\n")
    assert _score(syms[0], _tokens("zebra quantum walrus")) == 0.0


def test_cos_basics():
    assert _cos([1.0, 0.0], [1.0, 0.0]) == 1.0
    assert _cos([1.0, 0.0], [0.0, 1.0]) == 0.0
    assert _cos([0.0, 0.0], [1.0, 0.0]) == 0.0     # zero vector guarded


def test_call_graph_expansion_includes_callee():
    idx = _mkindex({"m.py": (
        "def orchestrate_payment(x):\n    return _mangled_zz(x)\n\n"
        "def _mangled_zz(x):\n    return x * 3\n")})
    q = "how does orchestrate payment work"
    # without expansion the weird-named callee is not matched
    r0 = retrieve(idx, q, k=8, expand=False, rerank=False)
    assert {s.name for s in r0["symbols"]} == {"orchestrate_payment"}
    # 1-hop expansion pulls in the callee
    r1 = retrieve(idx, q, k=8, expand=True, rerank=False)
    assert {"orchestrate_payment", "_mangled_zz"} <= {s.name for s in r1["symbols"]}


def test_expansion_includes_callers_too():
    idx = _mkindex({"m.py": (
        "def target_thing(x):\n    return x\n\n"
        "def unrelated_caller(y):\n    return target_thing(y)\n")})
    r = retrieve(idx, "target thing", k=8, expand=True, rerank=False)
    assert "unrelated_caller" in {s.name for s in r["symbols"]}


def test_k_respected():
    files = {f"m{i}.py": f"def widget_maker_{i}():\n    return {i}\n" for i in range(6)}
    idx = _mkindex(files)
    r = retrieve(idx, "widget maker", k=3, rerank=False, expand=False)
    assert len(r["symbols"]) == 3


def test_token_budget_respected():
    body = "".join(f"    x{i} = {i}\n" for i in range(30))
    files = {f"m{i}.py": f"def widget_{i}():\n{body}    return 0\n" for i in range(4)}
    idx = _mkindex(files)
    small = retrieve(idx, "widget", k=8, token_budget=250, rerank=False, expand=False)
    big = retrieve(idx, "widget", k=8, token_budget=100000, rerank=False, expand=False)
    assert len(small["symbols"]) < len(big["symbols"])
    assert small["tokens"] <= 250
    # NOTE (documented behavior): the FIRST slice is always returned even if it
    # alone exceeds the budget (the `and chosen` clause) -- never return nothing.
    tiny = retrieve(idx, "widget", k=8, token_budget=1, rerank=False, expand=False)
    assert len(tiny["symbols"]) == 1 and tiny["tokens"] > 1


def test_rerank_false_deterministic():
    files = {f"m{i}.py": f"def handler_{i}():\n    return {i}\n" for i in range(5)}
    idx = _mkindex(files)
    r1 = retrieve(idx, "handler", k=5, rerank=False)
    r2 = retrieve(idx, "handler", k=5, rerank=False)
    assert [s.id for s in r1["symbols"]] == [s.id for s in r2["symbols"]]
    assert r1["context"] == r2["context"]


def test_empty_query_returns_nothing():
    idx = _mkindex({"m.py": "def something():\n    return 1\n"})
    r = retrieve(idx, "", rerank=False)
    assert r["symbols"] == [] and r["context"] == "" and r["tokens"] == 0


def test_context_block_format():
    idx = _mkindex({"m.py": "def fmt_check():\n    return 1\n"})
    r = retrieve(idx, "fmt check", k=1, rerank=False)
    s = r["symbols"][0]
    assert r["context"].startswith(f"# {s.file}:{s.start_line}-{s.end_line}")
    assert "def fmt_check()" in r["context"]


if __name__ == "__main__":
    import pytest
    raise SystemExit(pytest.main([__file__, "-q"]))
