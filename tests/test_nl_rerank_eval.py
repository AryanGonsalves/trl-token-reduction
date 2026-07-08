"""Offline tests for the hosted-rerank eval harness: cost-cap safety (preflight +
running guard, no anthropic import) and the eval plumbing (candidates -> rerank ->
recall + non-inferiority) on a synthetic index."""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import pytest
import validate.nl_rerank_validate as V
from trl.retrieval import build_index


def test_static_worst_case_within_cap():
    # sizing guard: the full eval's printed worst-case must stay <= the hard cap.
    calls = len(V.MODELS) * V.N_RUNS * (len(V.NL) + len(V.LOOP))
    assert V._worst_case_usd(calls) <= V.CAP_USD == 1.50


def test_cap_preflight_aborts_over_budget():
    save = V.CAP_USD; V.CAP_USD = 0.0001
    try:
        with pytest.raises(SystemExit):
            V._preflight(84, out=lambda *a: None)
    finally:
        V.CAP_USD = save


def test_cap_running_guard_blocks_over_budget_call():
    save = V.CAP_USD; V.CAP_USD = 0.0
    try:
        with pytest.raises(RuntimeError):
            V._capped(lambda p: ("0", 0.01), {"usd": 0.0})("x")
    finally:
        V.CAP_USD = save


def test_eval_plumbing_reranks_and_holds_noninferiority(tmp_path):
    (tmp_path / "svc.py").write_text(
        "def rate_limit(n):\n    # guard against excessive calls per second\n    return n\n\n"
        "def other_fn(n):\n    return n\n")
    idx = build_index(str(tmp_path))
    # NL query shares NO words with the gold's name/doc -> keyword AND doc_boost miss;
    # only the (oracle) reranker, which knows the answer, can recover it.
    nl = [("how do we slow users typing too fast", "rate_limit", "svc.py")]
    loop = [("rate_limit throttle", "rate_limit", "svc.py")]   # name match -> keyword nails it
    res = V.run_eval(V._oracle_factory(nl, loop), ["m"], 2,
                     out=lambda *a: None, idx=idx, nl=nl, loop=loop)
    assert res["db_nl"] == 0                     # doc_boost misses this NL query
    assert res["detail"]["m"]["nl"] == [1, 1]    # rerank recovers it, both runs
    assert res["beat"] is True and res["noninf"] is True
