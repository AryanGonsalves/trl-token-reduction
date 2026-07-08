"""trl/engine.py — Engine.process on empty/degenerate inputs and lever on/off
configs. Run: python tests/test_engine_process.py"""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from trl import Engine
from trl.engine import Result
from trl.message import Message, SYSTEM, HISTORY, TOOL_RESULT, USER_QUERY

NOISE = "\n".join(["the same noisy line again"] * 30)


def _msgs():
    return [Message("system", SYSTEM, "You are an agent."),
            Message("tool", TOOL_RESULT, NOISE),
            Message("user", USER_QUERY, "live question?")]


def test_empty_messages():
    r = Engine({}).process([])
    assert isinstance(r, Result)
    assert r.messages == [] and r.cache_prefix_tokens == 0
    assert r.meta["tokens_before"] == 0 and r.meta["tokens_after"] == 0
    assert r.meta["tokens_removed"] == 0
    assert r.meta["messages_compressed"] == 0


def test_none_config():
    r = Engine(None).process(_msgs())
    assert isinstance(r, Result)
    # defaults: cache on, compression on, safe mode, provider none
    assert r.meta["mode"] == "safe"
    assert r.meta["local_model_used"] is False
    assert r.cache_prefix_tokens > 0
    assert r.meta["tokens_after"] <= r.meta["tokens_before"]


def test_empty_dict_config_defaults():
    eng = Engine({})
    assert eng.use_cache is True
    assert eng.compress_history is True and eng.compress_tool_outputs is True
    assert eng.mode == "safe"
    r = eng.process(_msgs())
    assert r.meta["messages_compressed"] == 1     # noisy tool output folded


def test_cache_off():
    cfg = {"arms": {"treatment": {"native_prompt_cache": False}}}
    r = Engine(cfg).process(_msgs())
    assert r.cache_prefix_tokens == 0
    # compression still runs (its flags default True)
    assert r.meta["tokens_after"] < r.meta["tokens_before"]


def test_compress_off():
    cfg = {"arms": {"treatment": {"compress_history": False,
                                  "compress_tool_outputs": False}}}
    r = Engine(cfg).process(_msgs())
    assert r.messages == _msgs()                  # tail untouched
    assert r.meta["tokens_removed"] == 0
    assert "messages_compressed" not in r.meta    # compression never ran
    assert r.cache_prefix_tokens > 0              # cache lever still on


def _msgs_both():
    # both a HISTORY and a TOOL_RESULT message, each independently compressible
    return [Message("system", SYSTEM, "You are an agent."),
            Message("assistant", HISTORY, NOISE),
            Message("tool", TOOL_RESULT, NOISE),
            Message("user", USER_QUERY, "live question?")]


def test_only_history_compressed():
    # compress_history on, compress_tool_outputs off -> history folded, tool
    # output left byte-identical (the flags act independently).
    cfg = {"arms": {"treatment": {"compress_history": True,
                                  "compress_tool_outputs": False}}}
    r = Engine(cfg).process(_msgs_both())
    hist = [m for m in r.messages if m.kind == HISTORY]
    tool = [m for m in r.messages if m.kind == TOOL_RESULT]
    assert r.meta["messages_compressed"] == 1
    assert tool and tool[0].content == NOISE          # tool output untouched
    assert hist and len(hist[0].content) < len(NOISE) # history compressed


def test_only_tool_outputs_compressed():
    # mirror: compress_tool_outputs on, compress_history off.
    cfg = {"arms": {"treatment": {"compress_history": False,
                                  "compress_tool_outputs": True}}}
    r = Engine(cfg).process(_msgs_both())
    hist = [m for m in r.messages if m.kind == HISTORY]
    tool = [m for m in r.messages if m.kind == TOOL_RESULT]
    assert r.meta["messages_compressed"] == 1
    assert hist and hist[0].content == NOISE          # history untouched
    assert tool and len(tool[0].content) < len(NOISE) # tool output compressed


def test_live_query_never_touched():
    r = Engine({}).process(_msgs())
    assert r.messages[-1].content == "live question?"
    assert r.messages[-1].kind == USER_QUERY


def test_meta_accounting_consistent():
    from trl.util import count_tokens
    msgs = _msgs()
    r = Engine({}).process(msgs)
    assert r.meta["tokens_before"] == sum(count_tokens(m.content) for m in msgs)
    assert r.meta["tokens_after"] == sum(count_tokens(m.content) for m in r.messages)
    assert r.meta["tokens_removed"] == r.meta["tokens_before"] - r.meta["tokens_after"]
    assert r.meta["tokens_removed"] > 0


def test_local_model_used_true_for_mock():
    # FIXED (P2): the mock provider runs the smart_compress stand-in, so
    # local_model_used must be True (it reported available()==False before).
    cfg = {"local_model": {"provider": "mock"}}
    r = Engine(cfg).process(_msgs())
    assert r.meta["local_model_used"] is True
    assert r.meta["local_model_provider"] == "mock"
    assert r.meta["messages_compressed"] == 1


def test_local_model_used_false_for_none():
    r = Engine({"local_model": {"provider": "none"}}).process(_msgs())
    assert r.meta["local_model_used"] is False
    assert r.meta["local_model_provider"] == "none"


def test_cache_settled_tokens_covers_more_than_system():
    # O1: settled cache region (system + folded history) >= system-only prefix.
    r = Engine({}).process(_msgs_both())
    assert r.meta["cache_settled_tokens"] >= r.meta["cache_prefix_tokens"] > 0


def test_cache_prefix_tokens_in_meta():
    # FIXED (P3): cache prefix tokens surfaced in meta (a saving tokens_removed
    # -- compression-only -- doesn't capture).
    r = Engine({}).process(_msgs())
    assert r.meta["cache_prefix_tokens"] == r.cache_prefix_tokens > 0


def test_result_sane_when_nothing_to_do():
    msgs = [Message("user", USER_QUERY, "hi")]
    r = Engine({}).process(msgs)
    assert r.messages == msgs
    assert r.cache_prefix_tokens == 0             # no stable prefix
    assert r.meta["tokens_removed"] == 0


if __name__ == "__main__":
    test_empty_messages()
    test_none_config()
    test_empty_dict_config_defaults()
    test_cache_off()
    test_compress_off()
    test_only_history_compressed()
    test_only_tool_outputs_compressed()
    test_live_query_never_touched()
    test_meta_accounting_consistent()
    test_local_model_used_true_for_mock()
    test_local_model_used_false_for_none()
    test_cache_settled_tokens_covers_more_than_system()
    test_cache_prefix_tokens_in_meta()
    test_result_sane_when_nothing_to_do()
    print("ALL ENGINE TESTS PASSED")
