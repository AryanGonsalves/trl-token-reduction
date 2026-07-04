"""Maximally-instrumented Claude probe: prints every step (flushed) with a short
timeout, so it reports the real failure instead of hanging. Then, only if the bare
call works, runs the naive-vs-proxy compression comparison."""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
print("step: start", flush=True)
import anthropic
print("step: imported anthropic", anthropic.__version__, flush=True)
from trl import Engine
from trl.util import load_config
from proxy.transform import transform_anthropic_request
print("step: imported trl/proxy", flush=True)

MODEL = os.environ.get("ANTHROPIC_MODEL", "claude-haiku-4-5-20251001")
KEY = os.environ.get("ANTHROPIC_API_KEY", "")
print(f"step: model={MODEL}  key_set={bool(KEY)}  key_prefix={KEY[:8]}", flush=True)

client = anthropic.Anthropic(max_retries=0, timeout=20)
print("step: client constructed; making bare 'hi' call...", flush=True)
try:
    r = client.messages.create(model=MODEL, max_tokens=8,
                               messages=[{"role": "user", "content": "Reply with: hi"}])
    txt = "".join(b.text for b in r.content if getattr(b, "type", "") == "text")
    print(f"BARE CALL OK -> {txt!r}  input_tokens={r.usage.input_tokens}", flush=True)
except Exception as e:
    print(f"BARE CALL FAILED: {type(e).__name__}: {str(e)[:300]}", flush=True)
    print("DONE"); sys.exit(0)

# full comparison
def ask(system, messages):
    r = client.messages.create(model=MODEL, system=system, messages=messages, max_tokens=16)
    text = "".join(b.text for b in r.content if getattr(b, "type", "") == "text").strip()
    u = r.usage
    return text, (u.input_tokens + (getattr(u, "cache_read_input_tokens", 0) or 0)
                  + (getattr(u, "cache_creation_input_tokens", 0) or 0))

noise = "\n".join(['{"note":"no action required","trace":"span"}'] * 30)
req = {"model": MODEL, "max_tokens": 16,
       "system": "You are a finance agent. Follow data exactly. " * 40,
       "messages": [
           {"role": "user", "content": "Batch:\n" + noise + '\n  "amount_usd": 7391,\n' + noise},
           {"role": "assistant", "content": "Loaded. " * 12},
           {"role": "user", "content": "What is amount_usd? Reply only the integer."}]}
print("step: naive call...", flush=True)
ab, tb = ask(req["system"], req["messages"])
cfg = load_config("config.yaml"); cfg["local_model"]["provider"] = "mock"
nr, _ = transform_anthropic_request(req, Engine(cfg))
print("step: proxy call...", flush=True)
ap, tp = ask(nr["system"], nr["messages"])
print(f"NAIVE  billed input tokens = {tb}  answer={ab!r}", flush=True)
print(f"PROXY  billed input tokens = {tp}  answer={ap!r}", flush=True)
print(f"-> {round(100*(1-tp/tb))}% fewer billed tokens; correct(7391): {'7391' in ab and '7391' in ap}", flush=True)
print("DONE")
