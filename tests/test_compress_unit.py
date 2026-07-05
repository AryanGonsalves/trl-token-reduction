"""trl/compress.py — _preserve_facts edge cases + compress_request modes and
thresholds. Run: python tests/test_compress_unit.py"""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from trl.compress import _preserve_facts, _aggressive, compress_request
from trl.local_model import LocalModel
from trl.message import Message, SYSTEM, HISTORY, TOOL_RESULT, USER_QUERY

LM_NONE = LocalModel({"provider": "none"})
LM_MOCK = LocalModel({"provider": "mock"})


# ---------------- _preserve_facts ----------------
def test_preserve_decimal_number():
    # the regex has no decimal support: "3.14" is seen as "3" and "14"; both
    # must survive, so the carrying line gets re-injected when missing.
    out = _preserve_facts("pi is 3.14 exactly", "pi is mentioned")
    assert "3.14" in out
    # already present -> nothing re-injected
    out2 = _preserve_facts("pi is 3.14 exactly", "we keep pi is 3.14 here")
    assert out2 == "we keep pi is 3.14 here"


def test_preserve_comma_number():
    out = _preserve_facts("total 1,000 units", "total units")
    assert "1,000" in out
    # compressed carrying the de-comma'd form counts as preserved
    out2 = _preserve_facts("total 1,000 units", "total 1000 units")
    assert out2 == "total 1000 units"


def test_preserve_negative_number():
    out = _preserve_facts("delta was -42 overnight", "delta shifted")
    assert "-42" in out


def test_preserve_number_already_present():
    out = _preserve_facts("order 555 shipped", "shipped order 555")
    assert out == "shipped order 555"      # untouched


def test_preserve_empty_original():
    assert _preserve_facts("", "whatever") == "whatever"


def test_preserve_no_numbers():
    assert _preserve_facts("just words here", "words") == "words"


def test_preserve_into_empty_compressed():
    # FIXED: when compressed=="" no leading blank line is prepended
    # (trl/compress.py:_preserve_facts).
    out = _preserve_facts("val 42", "")
    assert out == "val 42"
    assert "42" in out


def test_preserve_dedupes_reinjected_lines():
    orig = "id 99\nid 99\nid 99"
    out = _preserve_facts(orig, "nothing numeric")
    assert out.count("id 99") == 1


# ---------------- compress_request ----------------
def _long(tag, n=30):
    return "\n".join(f"{tag} filler line {tag}" for _ in range(n))


def test_under_threshold_untouched():
    # messages <= 200 chars are never compressible
    msgs = [Message("tool", TOOL_RESULT, "short output 123")]
    out, stats = compress_request(msgs, "safe", LM_NONE)
    assert out is msgs and stats == {"messages_compressed": 0}


def test_boundary_exactly_200_chars_untouched():
    msgs = [Message("tool", TOOL_RESULT, "x" * 200)]
    out, stats = compress_request(msgs, "safe", LM_NONE)
    assert stats["messages_compressed"] == 0


def test_empty_compressible_set_kinds():
    # stable prefix + live query are never compressible regardless of size
    msgs = [Message("system", SYSTEM, "S" * 500),
            Message("user", USER_QUERY, "Q" * 500)]
    out, stats = compress_request(msgs, "safe", LM_NONE)
    assert out is msgs and stats["messages_compressed"] == 0


def test_safe_mode_folds_tail_and_keeps_facts():
    noise = "\n".join(["the same line of noise"] * 30)
    msgs = [Message("system", SYSTEM, "sys"),
            Message("assistant", HISTORY, noise + "\namount_usd 4821"),
            Message("tool", TOOL_RESULT, noise),
            Message("user", USER_QUERY, "what is amount_usd?")]
    out, stats = compress_request(msgs, "safe", LM_NONE)
    assert stats["messages_compressed"] == 2
    # two compressible messages folded into ONE, in place
    kinds = [m.kind for m in out]
    assert kinds == [SYSTEM, HISTORY, USER_QUERY]
    blob = "\n".join(m.content for m in out)
    assert "4821" in blob, "fact guard failed"
    assert out[0].content == "sys" and out[-1].content == "what is amount_usd?"


def test_safe_mode_never_expands():
    text = _long("unique%d" % 1)
    # every line unique -> heuristic can't shrink -> must return unchanged
    lines = "\n".join(f"unique line number {i}" for i in range(30))
    msgs = [Message("tool", TOOL_RESULT, lines)]
    out, stats = compress_request(msgs, "safe", LM_NONE)
    assert stats["messages_compressed"] == 0
    assert out[0].content == lines


def test_aggressive_mode_summarizes():
    noise = "\n".join(f"log entry {i} nothing to see" for i in range(40))
    msgs = [Message("tool", TOOL_RESULT, noise)]
    out, stats = compress_request(msgs, "aggressive", LM_NONE)
    assert stats["messages_compressed"] == 1
    assert "[summarized" in out[0].content
    assert len(out[0].content) < len(noise)


def test_aggressive_no_fact_guard():
    # aggressive is EXPECTED to be lossy: the fact guard is not applied
    noise = "\n".join(f"filler row {i}" for i in range(40))
    tail_fact = "the secret invoice is 98765"
    msgs = [Message("tool", TOOL_RESULT, noise + "\n" + tail_fact)]
    out, _ = compress_request(msgs, "aggressive", LM_NONE)
    assert "98765" not in out[0].content, "aggressive unexpectedly kept the tail fact"


def test_mock_mode_keeps_factish_lines():
    noise = "\n".join(["narrative filler with no facts at all"] * 30)
    msgs = [Message("tool", TOOL_RESULT, noise + "\nKEYFACT: order 771 refunded")]
    out, stats = compress_request(msgs, "safe", LM_MOCK)
    assert stats["messages_compressed"] == 1
    assert "771" in out[0].content


def test_all_boilerplate_keeps_message_nonblank():
    # FIXED: when the whole compressible tail is boilerplate (heuristic_compress
    # would return ""), compress_request declines to compress and leaves the
    # original message intact rather than blanking it
    # (trl/compress.py:compress_request).
    blob = "\n".join(["DEBUG noise line here"] * 15)
    assert len(blob) > 200
    msgs = [Message("tool", TOOL_RESULT, blob)]
    out, stats = compress_request(msgs, "safe", LM_NONE)
    assert stats["messages_compressed"] == 0
    assert out[0].content == blob          # unchanged, never blanked


if __name__ == "__main__":
    test_preserve_decimal_number()
    test_preserve_comma_number()
    test_preserve_negative_number()
    test_preserve_number_already_present()
    test_preserve_empty_original()
    test_preserve_no_numbers()
    test_preserve_into_empty_compressed()
    test_preserve_dedupes_reinjected_lines()
    test_under_threshold_untouched()
    test_boundary_exactly_200_chars_untouched()
    test_empty_compressible_set_kinds()
    test_safe_mode_folds_tail_and_keeps_facts()
    test_safe_mode_never_expands()
    test_aggressive_mode_summarizes()
    test_aggressive_no_fact_guard()
    test_mock_mode_keeps_factish_lines()
    test_all_boilerplate_keeps_message_nonblank()
    print("ALL COMPRESS UNIT TESTS PASSED")
