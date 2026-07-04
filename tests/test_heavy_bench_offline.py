"""Offline proof for validate/heavy_bench.py: fake clients only, NO network.

Asserts (1) the cost accounting math, (2) the pre-call guard stops BEFORE the
cap can be exceeded, (3) no real socket is ever opened, (4) the input cap
truncation works, (5) price fallback for unknown model strings.
"""
import os
import socket
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from validate import heavy_bench as hb


# ------------------------------------------------------------- fake clients
class _NS:
    def __init__(self, **kw):
        self.__dict__.update(kw)


def _openai_response(inp, cached, out, text="answer"):
    return _NS(choices=[_NS(message=_NS(content=text))],
               usage=_NS(prompt_tokens=inp, completion_tokens=out,
                         prompt_tokens_details=_NS(cached_tokens=cached)))


class FakeOpenAIClient:
    """Mimics openai.OpenAI shape; returns canned usage; counts calls."""
    def __init__(self, inp=12000, cached=0, out=300, text="answer"):
        self.calls = 0
        self._resp = _openai_response(inp, cached, out, text)
        self.chat = _NS(completions=_NS(create=self._create))

    def _create(self, **kw):
        self.calls += 1
        assert kw["max_completion_tokens"] == hb.MAX_OUTPUT_TOK
        return self._resp


class FakeAnthropicClient:
    def __init__(self, inp=5000, cache_read=1000, out=100, text="answer"):
        self.calls = 0
        self._resp = _NS(
            content=[_NS(type="text", text=text)],
            usage=_NS(input_tokens=inp, cache_read_input_tokens=cache_read,
                      cache_creation_input_tokens=0, output_tokens=out))
        self.messages = _NS(create=self._create)

    def _create(self, **kw):
        self.calls += 1
        assert kw["max_tokens"] == hb.MAX_OUTPUT_TOK
        return self._resp


class _NoNetwork:
    """socket.socket replacement that fails loudly if anything dials out."""
    def __init__(self, *a, **k):
        raise AssertionError("network access attempted during offline test")


@pytest.fixture
def no_network(monkeypatch):
    monkeypatch.setattr(socket, "socket", _NoNetwork)
    monkeypatch.setattr(socket, "create_connection", _NoNetwork)


def _tiny_task():
    return hb.Task("tiny",
                   [{"role": "user", "content": "baseline context question"}],
                   [{"role": "user", "content": "treatment question"}],
                   lambda text: "answer" in text, "answer")


# ------------------------------------------------------------- cost math
def test_cost_math_gpt55():
    b = hb.Budget("openai", "gpt-5.5")
    # 10000 in (4000 of them cached) + 300 out at gpt-5.5 prices:
    # (10000-4000)*5/1e6 + 4000*0.50/1e6 + 300*30/1e6 = .03 + .002 + .009
    cost = b.add({"input_tokens": 10000, "cached_input_tokens": 4000,
                  "output_tokens": 300})
    assert cost == pytest.approx(0.041)
    assert b.spent == pytest.approx(0.041)


def test_cost_math_opus48_and_accumulation():
    b = hb.Budget("anthropic", "claude-opus-4-8")
    u = {"input_tokens": 6000, "cached_input_tokens": 1000, "output_tokens": 200}
    # (5000*5 + 1000*0.5 + 200*25)/1e6 = 0.0305
    assert b.add(u) == pytest.approx(0.0305)
    b.add(u)
    assert b.spent == pytest.approx(0.061)
    assert b.calls == 2


def test_unknown_model_falls_back_to_default_prices():
    assert hb.Budget("openai", "gpt-7-experimental").prices == hb.PRICES["gpt-5.5"]
    assert (hb.Budget("anthropic", "claude-opus-9").prices
            == hb.PRICES["claude-opus-4-8"])


def test_worst_case_is_conservative():
    b = hb.Budget("openai", "gpt-5.5")
    # (12000*5 + 300*30)/1e6 = 0.069 -- an actual capped call can never cost more
    assert b.worst_case_call_cost() == pytest.approx(0.069)


# ------------------------------------------------------- the HARD cost cap
def test_guard_stops_before_exceeding_cap(no_network):
    """Simulate expensive calls (worst-case-sized usage) against a small cap:
    the pre-call guard must stop BEFORE the second call, and spend <= cap."""
    fake = FakeOpenAIClient(inp=12000, cached=0, out=300)   # $0.069/call
    prov = hb.OpenAIProvider("gpt-5.5", client=fake)
    budget = hb.Budget("openai", "gpt-5.5", cap=0.10)
    res = hb.run_provider(prov, budget, [_tiny_task(), _tiny_task()])
    assert fake.calls == 1                    # 2nd call never fired
    assert res["stopped_early"] is True
    assert res["spent"] == pytest.approx(0.069)
    assert res["spent"] <= budget.cap         # NEVER exceeds the cap
    assert len(res["rows"]) == 0              # no fully-completed task pair


def test_guard_zero_budget_makes_zero_calls(no_network):
    fake = FakeOpenAIClient()
    prov = hb.OpenAIProvider("gpt-5.5", client=fake)
    budget = hb.Budget("openai", "gpt-5.5", cap=0.01)  # below worst-case
    res = hb.run_provider(prov, budget, [_tiny_task()])
    assert fake.calls == 0 and res["spent"] == 0.0 and res["stopped_early"]


def test_full_run_under_real_cap_offline(no_network):
    """Both providers via fake clients: math flows end-to-end, cap respected,
    quality verification wired through."""
    ftask = _tiny_task()
    fo = FakeOpenAIClient(inp=9000, cached=0, out=50, text="the answer is X")
    ro = hb.run_provider(hb.OpenAIProvider("gpt-5.5", client=fo),
                         hb.Budget("openai", "gpt-5.5"), [ftask])
    assert fo.calls == 2 and not ro["stopped_early"]
    assert ro["spent"] == pytest.approx(2 * (9000 * 5 + 50 * 30) / 1e6)
    assert ro["rows"][0]["baseline"]["correct"] is True

    fa = FakeAnthropicClient(inp=5000, cache_read=1000, out=100, text="no idea")
    ra = hb.run_provider(hb.AnthropicProvider("claude-opus-4-8", client=fa),
                         hb.Budget("anthropic", "claude-opus-4-8"), [ftask])
    assert fa.calls == 2 and not ra["stopped_early"]
    # Anthropic input_tokens EXCLUDES cache reads: total_in = 5000+1000 = 6000,
    # per call (5000*5 + 1000*0.5 + 100*25)/1e6 = 0.028
    assert ra["spent"] == pytest.approx(0.056)
    assert ra["rows"][0]["treatment"]["correct"] is False
    assert ro["spent"] <= hb.COST_CAP_USD and ra["spent"] <= hb.COST_CAP_USD


def test_api_error_stops_provider(no_network):
    class Boom:
        def __init__(self):
            self.chat = _NS(completions=_NS(create=self._create))
        def _create(self, **kw):
            raise RuntimeError("simulated API failure")
    res = hb.run_provider(hb.OpenAIProvider("gpt-5.5", client=Boom()),
                          hb.Budget("openai", "gpt-5.5"), [_tiny_task()])
    assert res["stopped_early"] and res["spent"] == 0.0


# ------------------------------------------------------------- input cap
def test_input_cap_truncates_oversized_context():
    huge = [{"role": "system", "content": "keep this"},
            {"role": "user", "content": "word " * 60000 + "\nQUESTION AT END?"}]
    capped = hb.fit_input_cap(huge)
    total = sum(hb.count_tokens(m["content"]) for m in capped)
    assert total <= hb.MAX_INPUT_TOK
    assert capped[1]["content"].endswith("QUESTION AT END?")   # tail survives
    assert capped[0]["content"] == "keep this"


def test_heavy_tasks_fit_cap_and_are_heavy():
    tasks = hb.make_tasks()
    assert len(tasks) == 3
    for t in tasks:
        base = sum(hb.count_tokens(m["content"]) for m in
                   hb.fit_input_cap(t.baseline_messages))
        treat = sum(hb.count_tokens(m["content"]) for m in
                    hb.fit_input_cap(t.treatment_messages))
        assert base <= hb.MAX_INPUT_TOK and treat <= hb.MAX_INPUT_TOK
        assert base > 4000            # genuinely heavy
        assert treat < base * 0.5     # the layer actually reduces
