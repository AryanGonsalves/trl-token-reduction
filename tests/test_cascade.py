"""Cascade unit test: quality stays at big-model level while big-model calls drop.
Run: python tests/test_cascade.py"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from bench.cascade_bench import run
from trl.cascade import cascade

def test_router_basic():
    # confident local -> no big call; unconfident -> escalate
    r1 = cascade("q", "", lambda q,c: ("42", True), lambda q,c: "BIG")
    r2 = cascade("q", "", lambda q,c: (None, False), lambda q,c: "BIG")
    assert r1.route == "local" and not r1.used_big and r1.answer == "42"
    assert r2.route == "big" and r2.used_big and r2.answer == "BIG"
    print("router OK")

def test_cascade_bench():
    res = run(n_lookup=24, n_reason=8)
    assert res["cascade_acc"] >= res["big_acc"] - 1e-9, "cascade lost quality"
    assert res["calls_saved_pct"] > 50, "cascade did not save calls"
    print(f"cascade OK: {res['calls_saved_pct']:.0f}% fewer big calls, quality-neutral")

if __name__ == "__main__":
    test_router_basic()
    test_cascade_bench()
    print("ALL CASCADE TESTS PASSED")
