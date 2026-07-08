"""General text/document retrieval: big token cut, no quality loss.
Run: python tests/test_text_retrieval.py"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from trl.retrieval import build_text_index, retrieve_text

def test_text_retrieval():
    from bench.text_retrieval_bench import run
    r = run(n_tasks=16)
    assert r["ni"]["treatment_success"] >= r["ni"]["baseline_success"] - 0.01, "quality regressed"
    assert r["mult"] > 3.0, f"reduction too small: {r['mult']:.1f}x"
    print(f"text retrieval OK: {r['mult']:.1f}x fewer tokens, quality-neutral")

def test_chunk_and_find():
    doc = ("INTRO\nsome preamble.\n\n"
           "BILLING\nRefunds are processed within 7 business days.\n\n"
           "SHIPPING\nThe free-shipping threshold is 75 dollars.\n")
    idx = build_text_index({"d.txt": doc})
    r = retrieve_text(idx, "what is the free shipping threshold?", token_budget=100, k=1, rerank=False)
    assert "75" in r["context"], "missed the right passage"
    print("chunk+find OK")

if __name__ == "__main__":
    test_chunk_and_find()
    test_text_retrieval()
    print("TEXT RETRIEVAL TESTS PASSED")


def test_retrieve_text_empty_query_returns_nothing():
    # FIX: an empty/whitespace question used to return an arbitrary first chunk;
    # now it returns nothing, matching code retrieve() semantics.
    from trl.retrieval.text_index import build_text_index, retrieve_text
    idx = build_text_index({"doc": "alpha para one.\n\nbeta para two.\n\ngamma three."})
    r = retrieve_text(idx, "   ", rerank=False)
    assert r["chunks"] == [] and r["context"] == "" and r["tokens"] == 0
