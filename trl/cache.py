"""Prefix caching — the single biggest lever for agents.

System prompt + tool schemas + long-lived context are identical on every step.
Native prompt caching lets us pay ~10% on the repeated prefix instead of full
freight. Here we just IDENTIFY the maximal stable prefix and report its token
count; the provider layer turns that into an actual cache marker
(anthropic cache_control / openai automatic caching)."""
from .message import STABLE_KINDS, USER_QUERY
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


def cacheable_prefix(messages):
    """(prefix_messages, prefix_tokens, n): the maximal SETTLED prefix -- every
    message up to (not including) the live user query. Unlike stable_prefix (which
    stops at the system/tool-schema header), this also covers prior turns and tool
    results: in an agent loop that whole region repeats byte-identically next step,
    so it is cacheable, not just the system header. Falls back to the stable prefix
    when there is no live user query to anchor on."""
    live = max((i for i, m in enumerate(messages) if m.kind == USER_QUERY),
               default=-1)
    if live <= 0:
        pref, tok = stable_prefix(messages)
        return pref, tok, len(pref)
    prefix = messages[:live]
    return prefix, sum(count_tokens(m.content) for m in prefix), len(prefix)
