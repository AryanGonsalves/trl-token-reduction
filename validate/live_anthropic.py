"""Live validation vs REAL Anthropic (Claude). Sends a bloated turn naively and
through our Anthropic transform (compression + cache_control on the prefix), and
compares Claude's OWN billed input tokens + the answer. Needs ANTHROPIC_API_KEY
(a small-budget key is fine). Cheap: 2 short haiku calls."""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import anthropic
from trl import Engine
from trl.util import load_config
from proxy.transform import transform_anthropic_request

MODEL = os.environ.get("ANTHROPIC_MODEL", "claude-haiku-4-5-20251001")
_client = None
def _c():
    global _client
    if _client is None:
        _client = anthropic.Anthropic(max_retries=1, timeout=20)
    return _client

def ask(system, messages):
    r = _c().messages.create(model=MODEL, system=system, messages=messages, max_tokens=16)
    text = "".join(b.text for b in r.content if getattr(b, "type", "") == "text").strip()
    u = r.usage
    total_in = (u.input_tokens + (getattr(u, "cache_read_input_tokens", 0) or 0)
                + (getattr(u, "cache_creation_input_tokens", 0) or 0))
    return text, total_in

def main():
    print(f"model: {MODEL}", flush=True)
    # quick connectivity/model probe first, so we see errors instead of hanging
    try:
        _c().messages.create(model=MODEL, max_tokens=4,
                             messages=[{"role": "user", "content": "ping"}])
        print("api reachable + model OK", flush=True)
    except Exception as e:
        print("PROBE FAILED:", type(e).__name__, str(e)[:200], flush=True)
        print("DONE"); return
    noise = "\n".join(['{"note":"no action required","trace":"span"}'] * 30)
    req = {"model": MODEL, "max_tokens": 16,
           "system": "You are a finance agent. Follow the data exactly. " * 40,
           "messages": [
               {"role": "user", "content": "Batch data:\n" + noise + '\n  "amount_usd": 7391,\n' + noise},
               {"role": "assistant", "content": "Loaded the batch. " * 12},
               {"role": "user", "content": "What is amount_usd? Reply with only the integer."}]}
    ab, tb = ask(req["system"], req["messages"])
    cfg = load_config("config.yaml"); cfg["local_model"]["provider"] = "mock"
    nr, _ = transform_anthropic_request(req, Engine(cfg))
    ap, tp = ask(nr["system"], nr["messages"])
    print(f"NAIVE  billed input tokens = {tb:>5}  answer = {ab!r}")
    print(f"PROXY  billed input tokens = {tp:>5}  answer = {ap!r}")
    print(f"-> {100*(1-tp/tb):.0f}% fewer billed tokens; correct(7391): {'7391' in ab and '7391' in ap}")
    print("DONE")

if __name__ == "__main__":
    main()
