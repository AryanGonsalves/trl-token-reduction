"""Prove real-provider usage parsing WITHOUT network/keys, using fake clients
shaped like the real SDK responses. Run: python tests/test_providers_shape.py"""
import sys, os, types
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from trl.message import Message, SYSTEM, TOOL_SCHEMA, TOOL_RESULT, USER_QUERY
from bench.task import Task
from bench.providers import AnthropicModel, OpenAIModel

CFG = {"big_model": {"anthropic_model": "x", "openai_model": "y"}}


def make_task():
    msgs = [Message("system", SYSTEM, "sys stable prompt " * 50),
            Message("system", TOOL_SCHEMA, "tool defs " * 50),
            Message("tool", TOOL_RESULT, 'noise\n"amount_usd": 300,\nnoise'),
            Message("user", USER_QUERY, "Sum amounts, integer only.")]
    return Task("t", msgs, "favorable", ['"amount_usd": 300'],
                lambda text: text.strip().endswith("300"), "Sum amounts, integer only.")


def ns(**k):  # tiny namespace
    return types.SimpleNamespace(**k)


def test_anthropic():
    m = AnthropicModel(CFG)
    fake_resp = ns(
        content=[ns(type="text", text="300")],
        usage=ns(input_tokens=100, output_tokens=5,
                 cache_read_input_tokens=900, cache_creation_input_tokens=0))
    m._client = ns(messages=ns(create=lambda **kw: _capture(kw, fake_resp)))
    r = m.call(make_task().messages, make_task(), 900, True)
    assert r.usage == {"input_tokens": 1000, "cached_input_tokens": 900,
                       "output_tokens": 5}, r.usage
    assert r.success is True
    # cache_control placed on system prefix when native_cache
    assert CAPTURED["system"][0]["cache_control"] == {"type": "ephemeral"}
    print("anthropic shape OK:", r.usage, "success=", r.success)


def test_openai():
    m = OpenAIModel(CFG)
    fake_resp = ns(
        choices=[ns(message=ns(content="300"))],
        usage=ns(prompt_tokens=1000, completion_tokens=5,
                 prompt_tokens_details=ns(cached_tokens=900)))
    m._client = ns(chat=ns(completions=ns(create=lambda **kw: _capture(kw, fake_resp))))
    r = m.call(make_task().messages, make_task(), 900, True)
    assert r.usage == {"input_tokens": 1000, "cached_input_tokens": 900,
                       "output_tokens": 5}, r.usage
    assert r.success is True
    assert CAPTURED["messages"][0]["role"] == "system"
    print("openai shape OK:  ", r.usage, "success=", r.success)


CAPTURED = {}
def _capture(kw, resp):
    CAPTURED.clear(); CAPTURED.update(kw); return resp


if __name__ == "__main__":
    test_anthropic()
    test_openai()
    print("ALL PROVIDER SHAPE TESTS PASSED")
