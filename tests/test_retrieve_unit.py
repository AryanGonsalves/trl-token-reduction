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
    # adaptive_budget=False -> strict legacy budgeting (the semantics under test)
    small = retrieve(idx, "widget", k=8, token_budget=250, rerank=False,
                     expand=False, adaptive_budget=False)
    big = retrieve(idx, "widget", k=8, token_budget=100000, rerank=False,
                   expand=False, adaptive_budget=False)
    assert len(small["symbols"]) < len(big["symbols"])
    assert small["tokens"] <= 250
    # NOTE (documented behavior): the FIRST slice is always returned even if it
    # alone exceeds the budget (the `and chosen` clause) -- never return nothing.
    tiny = retrieve(idx, "widget", k=8, token_budget=1, rerank=False,
                    expand=False, adaptive_budget=False)
    assert len(tiny["symbols"]) == 1 and tiny["tokens"] > 1


def test_adaptive_budget_default_fits_more_than_strict():
    # NEW default: adaptive_budget expands a tight budget to fit the top slices,
    # so it returns >= what strict budgeting would at the same token_budget.
    body = "".join(f"    x{i} = {i}\n" for i in range(30))
    files = {f"m{i}.py": f"def widget_{i}():\n{body}    return 0\n" for i in range(4)}
    idx = _mkindex(files)
    strict = retrieve(idx, "widget", k=8, token_budget=250, rerank=False,
                      expand=False, adaptive_budget=False)
    adaptive = retrieve(idx, "widget", k=8, token_budget=250, rerank=False,
                        expand=False, adaptive_budget=True)
    assert len(adaptive["symbols"]) >= len(strict["symbols"])
    assert adaptive["tokens"] >= strict["tokens"]


def test_rerank_false_deterministic():
    files = {f"m{i}.py": f"def handler_{i}():\n    return {i}\n" for i in range(5)}
    idx = _mkindex(files)
    r1 = retrieve(idx, "handler", k=5, rerank=False)
    r2 = retrieve(idx, "handler", k=5, rerank=False)
    assert [s.id for s in r1["symbols"]] == [s.id for s in r2["symbols"]]
    assert r1["context"] == r2["context"]


def test_rerank_rejects_unrelated_query():
    # FIXED (P2): with an embedder, an unrelated query used to fill k slots with
    # near-orthogonal noise (blended score is never <= 0). Now a semantic floor
    # (min_similarity) gates inclusion, so a genuinely unrelated query returns
    # nothing. A related query still surfaces matches (positive control).
    idx = _mkindex({"m.py": (
        "def widget_alpha():\n    return 1\n\n"
        "def widget_beta():\n    return 2\n")})

    def fake(texts):
        # symbols carry 'widget'; the vector is orthogonal to a non-widget query
        return [[1.0, 0.0] if "widget" in t else [0.0, 1.0] for t in texts]

    # unrelated query -> cosine 0 to every symbol -> nothing admissible
    r_none = retrieve(idx, "zebra quantum walrus", rerank=True, embedder=fake, k=8)
    assert r_none["symbols"] == []

    # related query -> cosine 1 -> symbols surface even with no keyword overlap
    r_hit = retrieve(idx, "widget stuff", rerank=True, embedder=fake, k=8)
    assert {s.name for s in r_hit["symbols"]} == {"widget_alpha", "widget_beta"}


def test_min_similarity_threshold_tunable():
    # min_similarity is a knob: 1.01 rejects everything semantic; 0.0 keeps the
    # pre-fix permissive behavior. (Default 0.10 is conservative -- needs real-
    # embedder validation before trusting for recall.)
    idx = _mkindex({"m.py": "def widget_alpha():\n    return 1\n"})

    def fake(texts):
        return [[1.0, 0.0] if "widget" in t else [0.3, 0.95] for t in texts]

    strict = retrieve(idx, "zzz", rerank=True, embedder=fake, k=8, min_similarity=1.01)
    loose = retrieve(idx, "zzz", rerank=True, embedder=fake, k=8, min_similarity=0.0)
    assert strict["symbols"] == []
    assert len(loose["symbols"]) == 1


def test_deprioritize_tests_ranks_impl_over_testfile():
    # Precision hygiene (opt-in): a keyword-dense TEST file that names a concept
    # should not outrank the real definition. deprioritize_tests reweights (never
    # drops) non-impl paths so the impl def ranks at/above the test symbol.
    import os, tempfile
    d = tempfile.mkdtemp()
    os.makedirs(os.path.join(d, "tests"))
    open(os.path.join(d, "svc.py"), "w").write(
        "def rank_slices(items):\n    # rank and budget the slices here\n"
        "    return sorted(items)\n")
    open(os.path.join(d, "tests", "test_svc.py"), "w").write(
        "def test_rank_slices_budget(items):\n"
        "    # rank slices budget rank slices budget rank slices\n"
        "    return rank_slices([3, 1, 2])\n")
    idx = build_index(d)
    q = "rank and budget the slices"
    on = [s.name for s in retrieve(idx, q, k=5, rerank=False,
                                   deprioritize_tests=True)["symbols"]]
    assert "rank_slices" in on, on
    if "test_rank_slices_budget" in on:
        assert on.index("rank_slices") <= on.index("test_rank_slices_budget"), on
    # default (flag off) must still return the impl symbol (no regression)
    idx.pop("_emb", None)
    off = [s.name for s in retrieve(idx, q, k=5, rerank=False,
                                    deprioritize_tests=False)["symbols"]]
    assert "rank_slices" in off, off


def _thing_index():
    return _mkindex({
        "a.py": "def find_thing(x):\n    return x\n",
        "b.py": "def helper(y):\n    # unrelated glue code\n    return y + 1\n",
        "c.py": "def process_thing(z):\n    return z\n",
    })


def test_local_rerank_reorders_via_ask():
    # OPT-IN LLM-rerank: the local model's pick overrides keyword rank. `helper`
    # has ZERO keyword overlap with "thing" but the model puts it first.
    import re as _re
    idx = _thing_index()

    def fake_ask(prompt):
        for line in prompt.splitlines():
            m = _re.match(r"(\d+)\. helper ", line)
            if m:
                return m.group(1)          # choose `helper` first
        return "0"

    out = retrieve(idx, "thing", k=3, rerank="local", ask=fake_ask)
    assert out["symbols"][0].name == "helper", [s.name for s in out["symbols"]]


def test_local_rerank_fails_safe_when_ask_raises():
    # if the local model raises, retrieval must not crash -> keyword ranking.
    idx = _thing_index()
    def boom(prompt):
        raise RuntimeError("local model unreachable")
    local = [s.name for s in retrieve(idx, "thing", k=3, rerank="local", ask=boom)["symbols"]]
    keyword = [s.name for s in retrieve(idx, "thing", k=3, rerank=False)["symbols"]]
    assert local == keyword, (local, keyword)


def test_local_rerank_off_by_default_ask_not_called():
    # the flag is truly opt-in: default retrieve() never touches `ask`.
    idx = _thing_index()
    calls = {"n": 0}
    def counting(prompt):
        calls["n"] += 1
        return "0"
    retrieve(idx, "thing", k=3, rerank=False, ask=counting)
    retrieve(idx, "thing", k=3, ask=counting)          # default rerank (embedding/keyword)
    assert calls["n"] == 0, "ask called without rerank='local'"
    retrieve(idx, "thing", k=3, rerank="local", ask=counting)
    assert calls["n"] == 1, "ask not called under rerank='local'"


def test_hosted_rerank_reorders_via_ask():
    # OPT-IN hosted rerank: an injected ask (no network) reorders like the local path.
    import re as _re
    idx = _thing_index()

    def fake_ask(prompt):
        for line in prompt.splitlines():
            m = _re.match(r"(\d+)\. helper ", line)
            if m:
                return m.group(1)
        return "0"
    out = retrieve(idx, "thing", k=3, rerank="hosted", ask=fake_ask)
    assert out["symbols"][0].name == "helper", [s.name for s in out["symbols"]]


def test_hosted_rerank_no_key_falls_back_to_keyword(monkeypatch):
    # no ANTHROPIC_API_KEY -> _hosted_ask returns None -> exactly keyword ranking.
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    idx = _thing_index()
    hosted = [s.name for s in retrieve(idx, "thing", k=3, rerank="hosted")["symbols"]]
    keyword = [s.name for s in retrieve(idx, "thing", k=3, rerank=False)["symbols"]]
    assert hosted == keyword


def test_hosted_rerank_api_error_falls_safe():
    # API error mid-rerank -> keyword ranking, never crashes.
    idx = _thing_index()
    def boom(prompt):
        raise RuntimeError("api error")
    hosted = [s.name for s in retrieve(idx, "thing", k=3, rerank="hosted", ask=boom)["symbols"]]
    keyword = [s.name for s in retrieve(idx, "thing", k=3, rerank=False)["symbols"]]
    assert hosted == keyword


def test_hosted_off_by_default_builds_no_client(monkeypatch):
    # A normal retrieve() must NEVER touch the hosted path (no client, no spend).
    import importlib
    R = importlib.import_module("trl.retrieval.retrieve")
    calls = {"n": 0}
    def spy():
        calls["n"] += 1
        return None
    monkeypatch.setattr(R, "_hosted_ask", spy)
    idx = _thing_index()
    retrieve(idx, "thing", k=3)                 # default rerank (embed/keyword)
    retrieve(idx, "thing", k=3, rerank=False)
    assert calls["n"] == 0, "hosted path touched without opt-in"
    retrieve(idx, "thing", k=3, rerank="hosted")   # opt-in -> builds ask once
    assert calls["n"] == 1


def test_config_rerank_model_is_single_source_of_truth():
    from trl.util import load_config
    assert load_config("config.yaml").get("rerank", {}).get("model") == "claude-haiku-4-5-20251001"


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
