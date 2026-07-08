"""Cascade lever: handle the easy majority of steps on the cheap LOCAL pipeline,
escalate only the hard ones to the expensive big model.

Governing rule (mirrors our whole thesis): only keep a local answer when it is
CHEAPLY VERIFIABLE. If the local pipeline can produce an answer it can check
(e.g. an exact value extracted from retrieved source), use it for ~$0. Otherwise
escalate -- never gamble quality to save a call. A false-accept (local confidently
wrong) is the only way cascade can hurt quality, so the accept-check is the whole
game; the benchmark measures it."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Optional, Tuple


@dataclass
class CascadeResult:
    answer: str
    route: str          # "local" | "big"
    used_big: bool


def cascade(query: str, context: str,
            local_answer: Callable[[str, str], Tuple[Optional[str], bool]],
            big_answer: Callable[[str, str], str]) -> CascadeResult:
    """local_answer -> (answer, confident). If confident, keep it (no big call);
    else escalate to big_answer (one big-model call)."""
    try:
        ans, confident = local_answer(query, context)
    except Exception:
        # Local pipeline unreachable / raised mid-call -> FAIL SAFE to the frontier
        # model rather than propagate. Never let a local failure break the request.
        ans, confident = None, False
    # Reject empty/blank answers even when the local pipeline claims confidence:
    # a blank is almost always a local-extraction failure, and accepting it is a
    # false-accept (the one way cascade can silently hurt quality). Escalate.
    if confident and ans is not None and ans.strip():
        return CascadeResult(ans, "local", False)
    return CascadeResult(big_answer(query, context), "big", True)
