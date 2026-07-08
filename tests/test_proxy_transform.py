"""Proxy transform: leaner request out, live query + facts preserved, no network.
Run: python tests/test_proxy_transform.py"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from trl import Engine
from trl.util import load_config
from proxy.transform import transform_chat_request

def test_transform_reduces_and_preserves():
    cfg = load_config("config.yaml"); cfg["local_model"]["provider"] = "mock"
    eng = Engine(cfg)
    bloat = ("\n".join(['{ "note":"no action required", "trace":"span" }']*20)
             + '\n  "amount_usd": 4821,\n'
             + "\n".join(['{ "note":"nothing to see" }']*20))
    req = {"model": "gpt-4.1", "messages": [
        {"role": "system", "content": "You are a finance agent. " * 30},
        {"role": "assistant", "content": "earlier: fetched the batch. " * 20},
        {"role": "tool", "content": bloat},
        {"role": "user", "content": "What is the amount_usd? Reply with the integer."},
    ]}
    new_req, meta = transform_chat_request(req, eng)
    assert meta["tokens_after"] < meta["tokens_before"], "no reduction"
    blob = "\n".join(m["content"] for m in new_req["messages"])
    assert "4821" in blob, "dropped the load-bearing fact!"          # guard works
    assert new_req["messages"][-1]["content"].startswith("What is the amount_usd"), \
        "live user query was altered"
    print(f"transform OK: {meta['tokens_before']} -> {meta['tokens_after']} tok "
          f"({meta['tokens_saved']} saved), fact + query preserved")


def test_anthropic_shape():
    from proxy.transform import transform_anthropic_request
    cfg = load_config("config.yaml"); cfg["local_model"]["provider"] = "mock"
    eng = Engine(cfg)
    noise = "\n".join(['{"note":"nothing"}'] * 25)
    req = {"model": "claude-x", "max_tokens": 16,
           "system": "You are an agent. " * 40,
           "messages": [
               {"role": "user", "content": "data:\n" + noise + '\n  "amount_usd": 5566,\n' + noise},
               {"role": "assistant", "content": "ok. " * 12},
               {"role": "user", "content": "What is amount_usd? integer only."}]}
    nr, meta = transform_anthropic_request(req, eng)
    assert meta["tokens_after"] < meta["tokens_before"]
    assert isinstance(nr["system"], list) and nr["system"][0]["cache_control"] == {"type": "ephemeral"}

    def _text(c):
        return c if isinstance(c, str) else "\n".join(b.get("text", "") for b in c)

    blob = nr["system"][0]["text"] + "\n" + "\n".join(_text(m["content"]) for m in nr["messages"])
    assert "5566" in blob and nr["messages"][-1]["content"].startswith("What is amount_usd")
    # O1: a SECOND cache breakpoint on the last settled message (before live turn)
    bps = [m for m in nr["messages"] if isinstance(m["content"], list)
           and any(b.get("cache_control") for b in m["content"])]
    assert len(bps) == 1, "expected a settled-history cache breakpoint"
    assert isinstance(nr["messages"][-1]["content"], str), "live turn must stay unmarked"
    print(f"anthropic transform OK: {meta['tokens_before']}->{meta['tokens_after']} tok, "
          f"cache_control + fact + query preserved")


def test_document_field():
    import random
    from trl.util import count_tokens
    cfg = load_config("config.yaml"); cfg["local_model"]["provider"] = "mock"
    eng = Engine(cfg)
    rng = random.Random(7); secs = []; facts = {}
    filler = "Long operational prose nobody needs. " * 20
    for i in range(30):
        t = f"topic_{i}"; code = rng.randint(1000, 9999); facts[t] = code
        secs.append(f"SECTION {i}: {t}.\n{filler}\nThe code for {t} is {code}.\n{filler}")
    doc = "\n\n".join(secs); target = list(facts)[13]; gold = str(facts[target])
    req = {"model": "gpt-4.1", "documents": [doc],
           "messages": [{"role": "user", "content": f"code for {target}? integer only."}]}
    nr, meta = transform_chat_request(req, eng)
    sent = sum(count_tokens(m["content"]) for m in nr["messages"] if isinstance(m["content"], str))
    assert "documents" not in nr, "documents not consumed"
    assert gold in "\n".join(m["content"] for m in nr["messages"]), "fact dropped"
    assert sent < count_tokens(doc) * 0.4, "retrieval didn't cut the doc"
    print(f"proxy document-retrieval OK: {count_tokens(doc)} -> {sent} tok, fact kept")

def test_tool_call_requests_pass_through_unchanged():
    """tool_calls / tool_call_id plumbing has strict ordering + field
    requirements; the transform must never scramble or strip it."""
    cfg = load_config("config.yaml"); cfg["local_model"]["provider"] = "mock"
    eng = Engine(cfg)
    req = {"model": "gpt-4.1", "messages": [
        {"role": "system", "content": "sys"},
        {"role": "user", "content": "do the thing"},
        {"role": "assistant", "content": None,
         "tool_calls": [{"id": "c1", "type": "function",
                         "function": {"name": "f", "arguments": "{}"}}]},
        {"role": "tool", "tool_call_id": "c1", "content": "result " * 100},
        {"role": "user", "content": "now summarize"},
    ]}
    new_req, meta = transform_chat_request(req, eng)
    assert new_req["messages"] == req["messages"], "tool-call request was mutated"
    assert meta["tokens_saved"] == 0
    print("tool-call passthrough OK")


if __name__ == "__main__":
    test_transform_reduces_and_preserves()
    test_anthropic_shape()
    test_document_field()
    test_tool_call_requests_pass_through_unchanged()
    print("PROXY TRANSFORM TEST PASSED")
