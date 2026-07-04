"""Prove Claude-Code-CLI parsing offline (no subscription needed here).
Run: python tests/test_claude_cli_parse.py"""
import sys, os, json
import pytest
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from trl.message import Message, SYSTEM, TOOL_SCHEMA, TOOL_RESULT, USER_QUERY
from bench.task import Task
from bench import providers
from bench.providers import ClaudeCLIModel, parse_claude_cli_json

SAMPLE = json.dumps({
    "type": "result", "subtype": "success", "is_error": False,
    "result": "300", "session_id": "sess_abc",
    "total_cost_usd": 0.0142,
    "usage": {"input_tokens": 120, "cache_creation_input_tokens": 0,
              "cache_read_input_tokens": 880, "output_tokens": 4},
})


def make_task():
    msgs = [Message("system", SYSTEM, "stable " * 40),
            Message("tool", TOOL_RESULT, '"amount_usd": 300'),
            Message("user", USER_QUERY, "Sum amounts, integer only.")]
    return Task("t", msgs, "favorable", ['"amount_usd": 300'],
                lambda text: text.strip().endswith("300"), "Sum amounts.")


@pytest.fixture
def monkey_stdout():
    return SAMPLE


def test_parser():
    r = parse_claude_cli_json(SAMPLE, make_task())
    assert r.usage["input_tokens"] == 1000, r.usage       # 120+880+0
    assert r.usage["cached_input_tokens"] == 880
    assert r.usage["output_tokens"] == 4
    assert r.usage["cli_cost_usd"] == 0.0142
    assert r.success is True
    print("parser OK:", {k: r.usage[k] for k in ("input_tokens", "cached_input_tokens", "output_tokens")})


def test_call_with_fake_subprocess(monkey_stdout):
    m = ClaudeCLIModel({"claude_cli": {"bin": "claude"}})

    class FakeProc:
        returncode = 0
        stdout = monkey_stdout
        stderr = ""

    import types
    fake_sub = types.SimpleNamespace(run=lambda *a, **k: FakeProc())
    import builtins
    real_import = builtins.__import__

    def fake_import(name, *a, **k):
        if name == "subprocess":
            return fake_sub
        return real_import(name, *a, **k)

    builtins.__import__ = fake_import
    try:
        r = m.call(make_task().messages, make_task(), 880, True)
    finally:
        builtins.__import__ = real_import
    assert r.success is True and r.usage["input_tokens"] == 1000
    print("call() via fake subprocess OK")


def test_dry():
    m = ClaudeCLIModel({"claude_cli": {}})
    r = m.call(make_task().messages, make_task(), 0, True, dry=True)
    assert r.text.startswith("[dry]")
    print("dry OK:", r.text[:40])


if __name__ == "__main__":
    test_parser()
    test_dry()
    test_call_with_fake_subprocess(SAMPLE)
    print("ALL CLAUDE-CLI TESTS PASSED")
