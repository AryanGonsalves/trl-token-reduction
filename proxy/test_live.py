"""Live proxy validation against a REAL OpenAI API: send the SAME bloated
agentic request (a) naively and (b) through our transform, and compare the
BILLED prompt tokens and the answer. Proves the proxy cuts real cost at equal
quality. Needs OPENAI_API_KEY. Cheap (2 short requests)."""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from openai import OpenAI
from trl import Engine
from trl.util import load_config
from proxy.transform import transform_chat_request

MODEL = os.environ.get("MODEL", "gpt-4o-mini")
_client = None


def _c():
    global _client
    if _client is None:
        _client = OpenAI(timeout=30, max_retries=3)
    return _client

# a realistic bloated agent turn: big cacheable prefix + verbose tool tail with a
# buried load-bearing fact + the live question.
noise = "\n".join(['{"note":"no action required for this record","trace":"span"}'] * 30)
messages = [
    {"role": "system", "content": "You are a finance-ops agent. Follow the data "
     "exactly; never invent numbers. " * 40},
    {"role": "user", "content": "Here is the transaction batch data:\n"
     + noise + '\n  "amount_usd": 7391,\n' + noise},
    {"role": "assistant", "content": "Understood -- I've loaded the batch. " * 12},
    {"role": "user", "content": "What is the amount_usd in that batch data above? "
     "Reply with ONLY the integer."},
]
req = {"model": MODEL, "messages": messages, "max_tokens": 16, "temperature": 0}


def call(r):
    resp = _c().chat.completions.create(**r)
    return (resp.choices[0].message.content or "").strip(), resp.usage.prompt_tokens


def main():
    cfg = load_config("config.yaml"); cfg["local_model"]["provider"] = "mock"
    eng = Engine(cfg)
    ans_b, tok_b = call(req)                         # naive
    new_req, meta = transform_chat_request(req, eng)
    ans_p, tok_p = call(new_req)                     # through our layer

    print(f"model: {MODEL}")
    print(f"NAIVE   billed prompt_tokens = {tok_b:>5}   answer = {ans_b!r}")
    print(f"PROXY   billed prompt_tokens = {tok_p:>5}   answer = {ans_p!r}")
    print(f"-> {tok_b - tok_p} fewer billed input tokens ({100*(1-tok_p/tok_b):.1f}% less)")
    ok = ("7391" in ans_b) and ("7391" in ans_p)
    print(f"-> both answers correct (7391): {ok}   (quality preserved: {ok})")
    print("DONE")


if __name__ == "__main__":
    main()
