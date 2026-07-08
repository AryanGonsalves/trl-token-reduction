"""REAL-token, HARD-COST-CAPPED multi-step proof of the caching lever (O1) on the
actual product path. Sends a few steps through transform_anthropic_request (which
cache-marks the system prefix + the O1 settled-history breakpoint) and reads the
Anthropic usage block to show cache_creation_input_tokens (first step, cache write)
vs cache_read_input_tokens (later steps, cache hit) -- the real-token confirmation
that the repeated prefix is being cached.

SAFETY (see CLAUDE.md): hard cost cap. Bounded steps, tiny max_tokens, conservative
(over-estimated) prices, a static pre-flight guard (refuses to run if worst-case
total could exceed the cap), and a running guard that aborts before any call that
could breach it. The cap logic is proven offline with a fake client (_selftest)
before this ever touches the network. No cache_control removed -- caching is the
whole point of THIS run, and its write cost is included in the worst case.
"""
import os, sys, json
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from trl import Engine
from trl.retrieval import build_index, retrieve
from trl.util import count_tokens, load_config
from proxy.transform import transform_anthropic_request

CAP_USD = 0.50            # HARD ceiling for the whole run
MAX_STEPS = 4
MAX_OUTPUT = 64
MODEL = os.environ.get("TRL_REAL_MODEL", "claude-haiku-4-5-20251001")
# Conservative (deliberately HIGH) prices per Mtok so worst-case is over-stated.
PRICE_IN = 5.0; PRICE_OUT = 25.0
CACHE_WRITE_MULT = 1.25; TOK_FACTOR = 1.6   # tiktoken underestimates Anthropic billing
MAX_INPUT_TOK_PER_CALL = 6000               # refuse anything that isn't retrieval-lean

QUESTIONS = [
    "how does compress_request shrink the tail?",
    "how does cascade decide local vs escalate?",
    "what does stable_prefix mark for caching?",
    "how does _preserve_facts guard numbers?",
]


def _worst_case_usd(est_input_tok):
    return (est_input_tok * TOK_FACTOR * PRICE_IN * CACHE_WRITE_MULT
            + MAX_OUTPUT * PRICE_OUT) / 1e6


def _stable_system(index):
    """A large, STABLE system prefix (same every step) that a real coding agent
    carries -- instructions + a repo map. Must exceed Anthropic's minimum cacheable
    prefix (2048 tok Haiku / 1024 Sonnet) or the API silently skips caching."""
    guide = ("You are a coding agent operating inside a fixed repository. Follow these "
             "rules consistently on every turn: prefer precise, grounded answers; cite "
             "file and symbol names; never invent APIs; keep answers brief and correct. ") * 10
    files = sorted({s.file.split("/")[-1] for s in index["symbols"]})
    syms = sorted({s.name for s in index["symbols"]})[:500]
    repo_map = "Repository files:\n" + ", ".join(files) + "\n\nKnown symbols:\n" + ", ".join(syms)
    return guide + "\n\n" + repo_map


def _build_step_request(index, query, history, engine):
    r = retrieve(index, query, token_budget=800, k=6)
    sys_txt = _stable_system(index)
    msgs = []
    if history:
        msgs.append({"role": "user", "content": "prior notes:\n" + "\n".join(history)})
        msgs.append({"role": "assistant", "content": "noted."})
    msgs.append({"role": "user",
                 "content": f"{query}\n\nRelevant code:\n{r['context']}"})
    req = {"model": MODEL, "max_tokens": MAX_OUTPUT, "system": sys_txt, "messages": msgs}
    new_req, meta = transform_anthropic_request(req, engine)
    return new_req, meta


def _est_input_tok(req):
    def _t(c):
        if isinstance(c, str):
            return count_tokens(c)
        return sum(count_tokens(b.get("text", "")) for b in c)
    sys_tok = _t(req.get("system", "") if isinstance(req.get("system"), str)
                 else "".join(b.get("text", "") for b in req.get("system", [])))
    return sys_tok + sum(_t(m["content"]) for m in req["messages"])


def run(client_call, index=None):
    """client_call(req_dict) -> usage dict with input_tokens, output_tokens,
    cache_creation_input_tokens, cache_read_input_tokens. Injected so the cap logic
    is testable offline with a fake."""
    cfg = load_config("config.yaml"); cfg.setdefault("local_model", {})["provider"] = "mock"
    engine = Engine(cfg)
    if index is None:
        index = build_index(".")

    # ---- static pre-flight guard ----
    worst_per_call = _worst_case_usd(MAX_INPUT_TOK_PER_CALL)
    worst_total = worst_per_call * MAX_STEPS
    print(f"CAP ${CAP_USD:.2f} | worst-case/call ${worst_per_call:.4f} | "
          f"worst-case total ${worst_total:.4f} ({MAX_STEPS} steps)")
    if worst_total > CAP_USD:
        print("ABORT: worst-case total exceeds cap. Not starting."); return
    print(f"{'step':>4} {'in':>7} {'cache_write':>12} {'cache_read':>11} {'out':>5} {'$est':>8}")

    history, spent = [], 0.0
    for i in range(MAX_STEPS):
        q = QUESTIONS[i % len(QUESTIONS)]
        req, meta = _build_step_request(index, q, history, engine)
        est = _est_input_tok(req)
        if est > MAX_INPUT_TOK_PER_CALL:
            print(f"ABORT step {i}: est input {est} > {MAX_INPUT_TOK_PER_CALL}"); break
        # running guard: refuse the call if its worst case could breach the cap
        if spent + _worst_case_usd(est) > CAP_USD:
            print(f"STOP before step {i}: would risk exceeding cap (spent ${spent:.4f})"); break
        u = client_call(req)
        cw = u.get("cache_creation_input_tokens", 0); cr = u.get("cache_read_input_tokens", 0)
        it = u.get("input_tokens", 0); ot = u.get("output_tokens", 0)
        # actual cost (cache read billed ~0.1x, write ~1.25x, fresh input 1x)
        call_usd = ((it + 1.25 * cw + 0.1 * cr) * PRICE_IN + ot * PRICE_OUT) / 1e6
        spent += call_usd
        print(f"{i:>4} {it:>7} {cw:>12} {cr:>11} {ot:>5} {spent:>8.4f}")
        history.append(f"Q: {q}\nA: (resolved) step_{i}_value = {1000 + i * 111}")
    print(f"TOTAL est spend ${spent:.4f} (cap ${CAP_USD:.2f})")
    print("Look for: cache_read RISING after step 0 -> the settled prefix is cached. DONE")


def _real_client():
    import anthropic
    client = anthropic.Anthropic()   # reads ANTHROPIC_API_KEY from env

    def call(req):
        r = client.messages.create(**req)
        u = r.usage
        return {"input_tokens": u.input_tokens, "output_tokens": u.output_tokens,
                "cache_creation_input_tokens": getattr(u, "cache_creation_input_tokens", 0) or 0,
                "cache_read_input_tokens": getattr(u, "cache_read_input_tokens", 0) or 0}
    return call


def _selftest():
    """Offline proof of the cap logic with a FAKE client -- no network."""
    calls = {"n": 0}

    def fake(req):
        calls["n"] += 1
        # step 0 writes cache; later steps read it (simulating O1 working)
        if calls["n"] == 1:
            return {"input_tokens": 40, "output_tokens": 20,
                    "cache_creation_input_tokens": 300, "cache_read_input_tokens": 0}
        return {"input_tokens": 60, "output_tokens": 20,
                "cache_creation_input_tokens": 20, "cache_read_input_tokens": 300}

    print("=== selftest: normal cap, should complete 4 steps ===")
    run(fake)
    assert calls["n"] == MAX_STEPS, calls["n"]

    print("\n=== selftest: tiny cap, static pre-flight must ABORT ===")
    global CAP_USD
    save = CAP_USD; CAP_USD = 0.0001
    before = calls["n"]
    run(fake)
    assert calls["n"] == before, "cap failed to abort before any call!"
    CAP_USD = save
    print("\nSELFTEST PASSED: cap aborts on tiny budget, completes under normal budget.")


if __name__ == "__main__":
    if "--selftest" in sys.argv:
        _selftest()
    else:
        if not os.environ.get("ANTHROPIC_API_KEY"):
            print("Set ANTHROPIC_API_KEY first. (Run --selftest for the offline cap proof.)")
            sys.exit(1)
        run(_real_client())
