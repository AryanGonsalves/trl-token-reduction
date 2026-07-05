"""Offline proof for bigcode_bench (no network): arms build from the real repo,
treatment reduces tokens, gold is present in the full-context baseline, and the
hard cost guard never overspends even with the larger input cap."""
import os, sys, socket
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import validate.bigcode_bench as bc
from trl.util import count_tokens


def test_arms_build_real_and_treatment_reduces():
    arms, whole = bc.build_arms(bc.REPO_DIR)
    assert count_tokens(whole) > 15000, "codebase context should be genuinely large"
    assert len(arms) == len(bc.TASKS)
    for t, base, treat in arms:
        bt = count_tokens(base[1]["content"]); tt = count_tokens(treat[1]["content"])
        assert tt < bt * 0.5, f"{t.name}: treatment should be much smaller"
        # gold must be present in the FULL baseline so a correct model CAN answer
        for g in t.gold:
            assert g.lower() in whole.lower(), f"gold {g} missing from codebase"
    print("arms build; treatment reduces; gold present in full context")


def test_cost_guard_never_overspends_at_large_cap():
    b = bc.BigBudget("openai", "gpt-5.5")
    # worst-case reflects the raised 34k input cap (not heavy_bench's 12k)
    assert 0.15 < b.worst_case_call_cost() < 0.40  # openai ~0.21
    b.cap = 0.30
    for _ in range(10):
        if not b.can_afford_next_call():
            break
        b.add({"input_tokens": 30000, "cached_input_tokens": 0, "output_tokens": 300})
    assert b.spent <= 0.30, "guard overspent"
    print("cost guard holds at large cap:", round(b.spent, 3))


def test_no_network_touched():
    orig = socket.socket
    socket.socket = lambda *a, **k: (_ for _ in ()).throw(AssertionError("network!"))
    try:
        bc.build_arms(bc.REPO_DIR)  # must be fully offline
    finally:
        socket.socket = orig
    print("no network touched building arms")


if __name__ == "__main__":
    test_arms_build_real_and_treatment_reduces()
    test_cost_guard_never_overspends_at_large_cap()
    test_no_network_touched()
    print("ALL BIGCODE-BENCH OFFLINE TESTS PASSED")
