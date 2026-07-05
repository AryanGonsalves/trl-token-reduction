"""trl/cascade.py — router edge cases: local-vs-big routing, verifiable/easy
detection, no false-accepts. Run: python tests/test_cascade_router.py"""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from trl.cascade import cascade, CascadeResult


def test_confident_none_still_escalates():
    # confident=True but answer=None must NOT be accepted (the `is not None`
    # guard) -- a local pipeline reporting confidence with no answer escalates.
    calls = {"big": 0}
    def big(q, c):
        calls["big"] += 1
        return "BIG"
    r = cascade("q", "ctx", lambda q, c: (None, True), big)
    assert r.route == "big" and r.used_big and r.answer == "BIG"
    assert calls["big"] == 1


def test_unconfident_answer_escalates():
    # a local ANSWER without confidence is a gamble -> must escalate
    r = cascade("q", "", lambda q, c: ("guess", False), lambda q, c: "BIG")
    assert r.route == "big" and r.used_big and r.answer == "BIG"


def test_confident_local_skips_big_entirely():
    calls = {"big": 0}
    def big(q, c):
        calls["big"] += 1
        return "BIG"
    r = cascade("q", "", lambda q, c: ("42", True), big)
    assert r.route == "local" and not r.used_big and r.answer == "42"
    assert calls["big"] == 0, "big model was called despite confident local answer"


def test_empty_string_confident_escalates():
    # FIXED: an empty-string answer, even with confident=True, is a local-pipeline
    # failure and must escalate rather than be accepted (trl/cascade.py:cascade).
    r = cascade("q", "", lambda q, c: ("", True), lambda q, c: "BIG")
    assert r.route == "big" and r.used_big and r.answer == "BIG"


def test_whitespace_only_confident_escalates():
    # A blank/whitespace-only answer is likewise rejected.
    r = cascade("q", "", lambda q, c: ("   \n ", True), lambda q, c: "BIG")
    assert r.route == "big" and r.answer == "BIG"


def test_query_and_context_forwarded():
    seen = {}
    def local(q, c):
        seen["local"] = (q, c)
        return None, False
    def big(q, c):
        seen["big"] = (q, c)
        return "A"
    cascade("the query", "the context", local, big)
    assert seen["local"] == ("the query", "the context")
    assert seen["big"] == ("the query", "the context")


def test_verifiable_lookup_local_unverifiable_escalates():
    # mirror of the bench's accept-check: local answers ONLY when it can extract
    # and verify a single unambiguous value; everything else escalates.
    facts = {"compute_1_1": "7"}
    def local(q, c):
        for name, val in facts.items():
            if name in q:
                return val, True          # extracted + verifiable -> confident
        return None, False                # reasoning question -> escalate
    def big(q, c):
        return "BIGANSWER"
    easy = cascade("what does compute_1_1 return?", "", local, big)
    hard = cascade("which function returns the largest value?", "", local, big)
    assert easy.route == "local" and easy.answer == "7" and not easy.used_big
    assert hard.route == "big" and hard.answer == "BIGANSWER" and hard.used_big


if __name__ == "__main__":
    test_confident_none_still_escalates()
    test_unconfident_answer_escalates()
    test_confident_local_skips_big_entirely()
    test_empty_string_confident_escalates()
    test_whitespace_only_confident_escalates()
    test_query_and_context_forwarded()
    test_verifiable_lookup_local_unverifiable_escalates()
    print("ALL CASCADE ROUTER TESTS PASSED")
