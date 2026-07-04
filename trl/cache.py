"""Prefix caching — the single biggest lever for agents.

System prompt + tool schemas + long-lived context are identical on every step.
Native prompt caching lets us pay ~10% on the repeated prefix instead of full
freight. Here we just IDENTIFY the maximal stable prefix and report its token
count; the provider layer turns that into an actual cache marker
(anthropic cache_control / openai automatic caching)."""
from .message import STABLE_KINDS
from .util import count_tokens


def stable_prefix(messages):
    """Return (prefix_messages, prefix_tokens). The prefix is the leading run of
    stable-kind messages — the part that's byte-identical across agent steps."""
    prefix = []
    for m in messages:
        if m.kind in STABLE_KINDS:
            prefix.append(m)
        else:
            break
    return prefix, sum(count_tokens(m.content) for m in prefix)
