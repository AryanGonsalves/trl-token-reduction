"""trl/cache.py — stable_prefix: which kinds count, ordering, token count.
Run: python tests/test_cache_stable_prefix.py"""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from trl.cache import stable_prefix
from trl.message import (Message, SYSTEM, TOOL_SCHEMA, HISTORY, TOOL_RESULT,
                         USER_QUERY)
from trl.util import count_tokens


def _m(kind, content="x y z"):
    return Message("system", kind, content)


def test_stable_kinds_counted():
    msgs = [_m(SYSTEM, "sys prompt here"), _m(TOOL_SCHEMA, "tool schema here"),
            _m(HISTORY, "old turn"), _m(USER_QUERY, "live q")]
    prefix, toks = stable_prefix(msgs)
    assert [m.kind for m in prefix] == [SYSTEM, TOOL_SCHEMA]
    assert toks == count_tokens("sys prompt here") + count_tokens("tool schema here")


def test_prefix_stops_at_first_unstable():
    # a stable-kind message AFTER an unstable one must NOT count (byte-identity
    # of the prefix is the whole point)
    msgs = [_m(SYSTEM), _m(HISTORY), _m(TOOL_SCHEMA), _m(SYSTEM)]
    prefix, _ = stable_prefix(msgs)
    assert len(prefix) == 1 and prefix[0].kind == SYSTEM


def test_no_stable_prefix():
    msgs = [_m(HISTORY), _m(SYSTEM)]
    prefix, toks = stable_prefix(msgs)
    assert prefix == [] and toks == 0


def test_empty_messages():
    prefix, toks = stable_prefix([])
    assert prefix == [] and toks == 0


def test_all_stable():
    msgs = [_m(SYSTEM, "a b c"), _m(TOOL_SCHEMA, "d e f"), _m(TOOL_SCHEMA, "g h i")]
    prefix, toks = stable_prefix(msgs)
    assert len(prefix) == 3
    assert toks == sum(count_tokens(m.content) for m in msgs)
    assert toks > 0


def test_unstable_kinds_never_in_prefix():
    for kind in (HISTORY, TOOL_RESULT, USER_QUERY):
        prefix, toks = stable_prefix([_m(kind, "leading unstable")])
        assert prefix == [] and toks == 0, kind


if __name__ == "__main__":
    test_stable_kinds_counted()
    test_prefix_stops_at_first_unstable()
    test_no_stable_prefix()
    test_empty_messages()
    test_all_stable()
    test_unstable_kinds_never_in_prefix()
    print("ALL CACHE PREFIX TESTS PASSED")
