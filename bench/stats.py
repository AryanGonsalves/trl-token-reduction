"""Non-inferiority test on paired task-success.

We do NOT report a point estimate and call it a day. We bootstrap a CI on the
paired delta (treatment - baseline) and check the lower bound against the
pre-registered margin. Deterministic given a seed."""
import random


def noninferiority(base_success, treat_success, margin, seed=7, iters=5000):
    """base/treat_success: parallel lists of 0/1, one per task (paired)."""
    n = len(base_success)
    assert n == len(treat_success) and n > 0
    pairs = list(zip(base_success, treat_success))
    obs_delta = _mean([t for _, t in pairs]) - _mean([b for b, _ in pairs])

    rng = random.Random(seed)
    deltas = []
    for _ in range(iters):
        sample = [pairs[rng.randrange(n)] for _ in range(n)]
        deltas.append(_mean([t for _, t in sample]) - _mean([b for b, _ in sample]))
    deltas.sort()
    lo = deltas[int(0.025 * iters)]
    hi = deltas[int(0.975 * iters)]

    return {
        "n": n,
        "baseline_success": _mean([b for b, _ in pairs]),
        "treatment_success": _mean([t for _, t in pairs]),
        "delta": obs_delta,
        "ci95": (lo, hi),
        "margin": -abs(margin),
        # PASS iff we can rule out a drop bigger than the margin
        "non_inferior": lo >= -abs(margin),
    }


def _mean(xs):
    return sum(xs) / len(xs) if xs else 0.0
