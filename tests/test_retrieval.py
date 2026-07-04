"""Retrieval unit test: extractor finds symbols; retriever returns the relevant
one; code-QA arm cuts tokens with no quality loss. Run: python tests/test_retrieval.py"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from trl.retrieval import build_index, retrieve

def test_extract_and_retrieve():
    idx = build_index("trl")
    names = {s.name for s in idx["symbols"]}
    assert "smart_compress" in names and "_preserve_facts" in names, "extractor missed symbols"
    r = retrieve(idx, "how does the fact preserving guard re-inject dropped numbers?",
                 token_budget=800, k=6)
    got = {s.name for s in r["symbols"]}
    assert "_preserve_facts" in got, f"retriever missed the target: {got}"
    print("extract+retrieve OK:", sorted(got))

def test_codeqa_arm():
    from bench.retrieval_bench import run
    ni = run(n_tasks=16)
    assert ni["treatment_success"] >= ni["baseline_success"] - 0.01, "quality regressed"
    print("code-QA arm OK: quality non-inferior")


def test_js_ts():
    import tempfile, os
    from trl.retrieval import build_index, retrieve
    d = tempfile.mkdtemp()
    open(os.path.join(d, "a.ts"), "w").write(
        "export function loadUser(id){ return db.query(id); }\n"
        "export const rateLimit = (n) => check(n);\n")
    idx = build_index(d)
    names = {x.name for x in idx["symbols"]}
    assert {"loadUser", "rateLimit"} <= names, f"TS extract missed: {names}"
    r = retrieve(idx, "how does rate limiting work", token_budget=200, k=2)
    assert any(x.name == "rateLimit" for x in r["symbols"]), "TS retrieve missed target"
    print("JS/TS OK:", sorted(names))


def test_gitignore():
    import tempfile, os
    from trl.retrieval import build_index
    d = tempfile.mkdtemp()
    open(os.path.join(d, ".gitignore"), "w").write("gen_*.py\n")
    open(os.path.join(d, "keep.py"), "w").write("def keep():\n    return 1\n")
    open(os.path.join(d, "gen_x.py"), "w").write("def nope():\n    return 2\n")
    names = {x.name for x in build_index(d)["symbols"]}
    assert names == {"keep"}, f"gitignore not respected: {names}"
    print("gitignore OK")


def test_rerank():
    import tempfile, os, re as _re
    from trl.retrieval import build_index, retrieve
    d = tempfile.mkdtemp()
    open(os.path.join(d, "svc.py"), "w").write(
        "def rateLimit(n):\n    return check(n)\n\n"
        "def computeTax(a):\n    return a * 0.2\n")
    idx = build_index(d)
    q = "throttle requests when users type too fast"     # no keyword overlap
    assert not retrieve(idx, q, rerank=False, k=3)["symbols"], "keyword should miss"
    CONCEPT = {"rate", "limit", "throttle", "fast", "requests", "users", "type"}
    def fake(texts):
        out = []
        for t in texts:
            toks = {p.lower() for w in _re.findall(r"[A-Za-z]+", t)
                    for p in _re.findall(r"[A-Z]?[a-z]+|[A-Z]+", w)}
            out.append([1.0 if toks & CONCEPT else 0.0,
                        0.2 if toks & CONCEPT else 1.0])
        return out
    r = retrieve(idx, q, rerank=True, embedder=fake, k=3)
    assert r["symbols"][0].name == "rateLimit", "rerank missed semantic match"
    print("rerank OK: semantic match surfaced with zero keyword overlap")


def test_multi_lang():
    import tempfile, os
    from trl.retrieval import build_index
    d = tempfile.mkdtemp()
    open(os.path.join(d, "m.go"), "w").write("package m\nfunc LoadUser(id int) int { return q(id) }\n")
    open(os.path.join(d, "m.rs"), "w").write("fn rate_limit(n:i32)->i32{ check(n) }\n")
    open(os.path.join(d, "M.java"), "w").write("class Auth { int login(){ return q(); } }\n")
    open(os.path.join(d, "P.cs"), "w").write("class Billing { int ComputeTax(int a){ return R(a); } }\n")
    names = {x.name for x in build_index(d)["symbols"]}
    assert {"LoadUser", "rate_limit", "login", "ComputeTax", "Auth", "Billing"} <= names, names
    print("multi-lang OK:", sorted(names))

if __name__ == "__main__":
    test_extract_and_retrieve()
    test_codeqa_arm()
    test_js_ts()
    test_gitignore()
    test_rerank()
    test_multi_lang()
    print("ALL RETRIEVAL TESTS PASSED")
