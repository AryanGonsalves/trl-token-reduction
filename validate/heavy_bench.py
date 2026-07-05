"""Heavy-task benchmark vs the MOST ADVANCED models (GPT-5.5 / Claude Opus 4.8)
with a HARD COST CAP so it can never overspend.

For each provider whose API key is in the environment, runs 3 HEAVY task pairs
(baseline = full bloated context; treatment = TRL-reduced context) and reports
billed tokens, dollars, % reduction and answer quality per arm.

THE COST GUARD (the part that matters, real money):
  * PRICES below, USD per 1M tokens. Unknown model string -> falls back to the
    provider default's prices so cost tracking always works.
  * MAX_OUTPUT_TOK caps max_tokens on every call; MAX_INPUT_TOK caps the input
    (task context is truncated to fit BEFORE sending).
  * BEFORE every call: worst_case = MAX_INPUT_TOK*in + MAX_OUTPUT_TOK*out.
    If cumulative_spent + worst_case > COST_CAP_USD the provider is STOPPED.
    Because every call's real cost is <= worst_case (input capped, output
    capped, no cache_control so no 1.25x cache-write premium), cumulative
    spend can never exceed COST_CAP_USD.
  * After every call the REAL billed usage is priced and added; running total
    printed. Clients use max_retries<=1 + timeout so a hang can't multiply cost.
  * Any API error -> stop that provider immediately (fail-safe with money).

Run:  OPENAI_API_KEY=... ANTHROPIC_API_KEY=... python -u validate/heavy_bench.py
Env:  OPENAI_MODEL (default gpt-5.5), ANTHROPIC_MODEL (default claude-opus-4-8)

Offline logic proof: tests/test_heavy_bench_offline.py (fake clients, no network).
"""
import os
import random
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from trl import Engine
from trl.util import load_config, count_tokens
from trl.retrieval import build_text_index, retrieve_text
from proxy.transform import transform_chat_request

# ---------------------------------------------------------------- COST GUARD
PRICES = {  # USD per 1M tokens
    "gpt-5.5":         {"in": 5.00, "out": 30.00, "cached": 0.50},
    "claude-opus-4-8": {"in": 5.00, "out": 25.00, "cached": 0.50},
}
COST_CAP_USD = 1.80      # per provider; hard stop
MAX_OUTPUT_TOK = 300     # max_tokens on every call
MAX_INPUT_TOK = 12000    # never send a request whose input exceeds this
# We count input with tiktoken; OpenAI bills the same, but Anthropic's tokenizer
# counts ~1.6x more. Inflate Anthropic's worst-case so the cap can never
# underestimate real spend (OpenAI stays 1.0).
_TOK_FACTOR = {"openai": 1.0, "anthropic": 1.6}

DEFAULT_MODEL = {"openai": "gpt-5.5", "anthropic": "claude-opus-4-8"}


class Budget:
    """Per-provider hard cost cap. can_afford_next_call() is checked BEFORE
    every call with a conservative worst-case; add() books the REAL usage."""

    def __init__(self, provider_name, model, cap=COST_CAP_USD):
        self.provider = provider_name
        self.model = model
        self.cap = cap
        self.spent = 0.0
        self.calls = 0
        # Unknown model string -> fall back to the provider default's prices.
        self.prices = PRICES.get(model) or PRICES[DEFAULT_MODEL[provider_name]]

    def worst_case_call_cost(self):
        p = self.prices
        f = _TOK_FACTOR.get(self.provider, 1.6)
        return (MAX_INPUT_TOK * f * p["in"] + MAX_OUTPUT_TOK * p["out"]) / 1e6

    def can_afford_next_call(self):
        return self.spent + self.worst_case_call_cost() <= self.cap

    def cost_of(self, usage):
        p = self.prices
        inp = int(usage.get("input_tokens", 0) or 0)
        cached = min(int(usage.get("cached_input_tokens", 0) or 0), inp)
        out = int(usage.get("output_tokens", 0) or 0)
        return ((inp - cached) * p["in"] + cached * p["cached"] + out * p["out"]) / 1e6

    def add(self, usage):
        cost = self.cost_of(usage)
        self.spent += cost
        self.calls += 1
        print(f"[budget] spent ${self.spent:.2f} of ${self.cap:.2f}", flush=True)
        return cost


# ------------------------------------------------------------ INPUT-SIZE CAP
def fit_input_cap(messages, cap=MAX_INPUT_TOK):
    """Return messages whose total content tokens fit under `cap` (with a small
    headroom for chat framing). Trims the LARGEST message from the middle so
    both the head (instructions) and the tail (question) survive."""
    msgs = [dict(m) for m in messages]
    marker = "\n...[truncated to fit input cap]...\n"
    for _ in range(200):  # hard bound, no infinite loop
        total = sum(count_tokens(m.get("content") or "") for m in msgs)
        if total <= cap - 64:
            break
        i = max(range(len(msgs)),
                key=lambda j: count_tokens(msgs[j].get("content") or ""))
        c = msgs[i].get("content") or ""
        if len(c) < 800:
            break
        cut = max(int(len(c) * 0.15), 400)
        mid = len(c) // 2
        msgs[i]["content"] = c[:mid - cut // 2] + marker + c[mid + cut // 2:]
    return msgs


# ----------------------------------------------------------------- PROVIDERS
class OpenAIProvider:
    name = "openai"

    def __init__(self, model, client=None):  # client injectable for offline tests
        self.model = model
        self._client = client

    def _c(self):
        if self._client is None:
            from openai import OpenAI
            # max_retries<=1 + timeout: a hang/retry can't multiply cost.
            self._client = OpenAI(timeout=120, max_retries=1)
        return self._client

    def call(self, messages):
        # max_completion_tokens: the accepted name on gpt-5.x (max_tokens is
        # rejected there); current SDKs accept it for older models too.
        r = self._c().chat.completions.create(
            model=self.model, messages=messages,
            max_completion_tokens=MAX_OUTPUT_TOK)
        text = (r.choices[0].message.content or "").strip()
        u = r.usage
        cached = 0
        det = getattr(u, "prompt_tokens_details", None)
        if det is not None:
            cached = getattr(det, "cached_tokens", 0) or 0
        return text, {"input_tokens": u.prompt_tokens,
                      "cached_input_tokens": cached,
                      "output_tokens": u.completion_tokens,
                      "stop": getattr(r.choices[0], "finish_reason", None)}


class AnthropicProvider:
    name = "anthropic"

    def __init__(self, model, client=None):
        self.model = model
        self._client = client

    def _c(self):
        if self._client is None:
            import anthropic
            self._client = anthropic.Anthropic(timeout=120, max_retries=1)
        return self._client

    @staticmethod
    def to_wire(messages):
        """OpenAI-format -> (system_text, anthropic messages). Merges consecutive
        same-role turns and guarantees the list starts with a user turn."""
        system_parts, turns = [], []
        for m in messages:
            role = m.get("role", "user")
            content = m.get("content") or ""
            if role == "system":
                system_parts.append(content)
                continue
            role = "assistant" if role == "assistant" else "user"
            if turns and turns[-1]["role"] == role:
                turns[-1]["content"] += "\n\n" + content
            else:
                turns.append({"role": role, "content": content})
        if turns and turns[0]["role"] != "user":
            turns.insert(0, {"role": "user", "content": "(context follows)"})
        if not turns:
            turns = [{"role": "user", "content": "(empty)"}]
        return "\n\n".join(system_parts), turns

    def call(self, messages):
        system, turns = self.to_wire(messages)
        kwargs = dict(model=self.model, max_tokens=MAX_OUTPUT_TOK, messages=turns)
        if system:
            kwargs["system"] = system  # plain string: NO cache_control -> no 1.25x write premium
        r = self._c().messages.create(**kwargs)
        text = "".join(b.text for b in r.content
                       if getattr(b, "type", "") == "text").strip()
        u = r.usage
        cache_read = getattr(u, "cache_read_input_tokens", 0) or 0
        cache_create = getattr(u, "cache_creation_input_tokens", 0) or 0
        total_in = u.input_tokens + cache_read + cache_create
        return text, {"input_tokens": total_in,
                      "cached_input_tokens": cache_read,
                      "output_tokens": u.output_tokens,
                      "stop": getattr(r, "stop_reason", None)}


# -------------------------------------------------------------- HEAVY TASKS
class Task:
    def __init__(self, name, baseline_messages, treatment_messages, verify, gold_desc):
        self.name = name
        self.baseline_messages = baseline_messages
        self.treatment_messages = treatment_messages
        self.verify = verify          # str -> bool
        self.gold_desc = gold_desc    # printable expected answer


_WORDS = ("this section provides general reference notes and background details "
          "that help readers understand the topic with simple everyday examples "
          "and clear explanations arranged in short easy to follow paragraphs").split()


def _prose(rng, n):
    return " ".join(rng.choice(_WORDS) for _ in range(n))


def _engine():
    cfg = load_config(os.path.join(ROOT, "config.yaml"))
    cfg.setdefault("local_model", {})["provider"] = "mock"  # offline preprocessor
    return Engine(cfg)


_DOC_FILES = ["README.md", "RUN.md", "COMPOSER_EXTENSION_SPEC.md",
              "extension/README.md", "plugin/INSTALL.md", "CONTRIBUTING.md"]


def _read_file(path):
    try:
        return open(os.path.join(ROOT, path), encoding="utf-8", errors="ignore").read()
    except Exception:
        return ""


def _real_corpus(target_tokens, files):
    """Concatenate REAL project files (non-templated, benign) up to ~target tokens.
    Real content avoids the refusal classifier that rejects synthetic templated text."""
    parts, tot = [], 0
    for f in files:
        txt = _read_file(f)
        if not txt.strip():
            continue
        parts.append("===== " + f + " =====\n" + txt)
        tot += count_tokens(txt)
        if tot >= target_tokens:
            break
    return "\n\n".join(parts)


def make_longdoc_task():
    """Heavy REAL-document QA: the project's own docs with one buried fact.
    Baseline: whole corpus. Treatment: retrieved passages only."""
    corpus = _real_corpus(6000, _DOC_FILES)
    gold = "62335"
    appendix = ("\n\n===== APPENDIX A: EVALUATION METADATA =====\n"
                "For internal bookkeeping, the archival index number assigned to "
                "this token-reduction evaluation corpus is " + gold + ". It is a "
                "plain catalog identifier with no other meaning.\n")
    mid = len(corpus) // 2
    doc = corpus[:mid] + appendix + corpus[mid:]
    q = ("What archival index number is assigned to this token-reduction "
         "evaluation corpus? Reply with only the integer.")
    sysmsg = {"role": "system",
              "content": "You answer questions using the provided project documentation."}
    baseline = [sysmsg, {"role": "user", "content": doc + "\n\n" + q}]
    idx = build_text_index({"project_docs.txt": doc})
    r = retrieve_text(idx, q, token_budget=500, k=4, rerank=False)
    treatment = [sysmsg, {"role": "user", "content": r["context"] + "\n\n" + q}]
    return Task("long_document_qa", baseline, treatment,
                lambda text: gold in text, gold)


def make_agent_turn_task():
    """Heavy agent turn over REAL content: system + redundant history + a large
    real doc dump carrying two buried numbers. Baseline: everything.
    Treatment: proxy transform (compressed tail + fact guard)."""
    system = ("You are a software support assistant. Answer the user's question "
              "using the diagnostic notes and files provided below.")
    dump_body = _real_corpus(4500, ["RUN.md", "plugin/INSTALL.md", "CONTRIBUTING.md",
                                     "COMPOSER_EXTENSION_SPEC.md", "extension/README.md"])
    lines = dump_body.split("\n")
    lines.insert(len(lines) // 3,
                 "metric total_prep_seconds: 48213 (wall-clock ms for the batch)")
    lines.insert(2 * len(lines) // 3,
                 "metric pieces_yielded: 37 (records emitted in this run)")
    tool_output = "Diagnostic notes from the most recent run:\n" + "\n".join(lines)
    history = []
    for k in range(4):
        history.append({"role": "user",
                        "content": "Update " + chr(65 + k) + ": please keep "
                        "reviewing the run notes."})
        history.append({"role": "assistant",
                        "content": "Understood, continuing to review the run notes."})
    question = ("From the diagnostic notes above, what are total_prep_seconds and "
                "pieces_yielded? Answer exactly as: "
                "total_prep_seconds=<integer>, pieces_yielded=<integer>")
    baseline = ([{"role": "system", "content": system}] + history
                + [{"role": "user", "content": tool_output},
                   {"role": "user", "content": question}])
    new_req, _meta = transform_chat_request(
        {"model": "bench", "messages": baseline}, _engine())
    treatment = new_req["messages"]

    def verify(text):
        return "48213" in text and re.search(r"\b37\b", text) is not None

    return Task("bloated_agent_turn", baseline, treatment, verify,
                "total_prep_seconds=48213, pieces_yielded=37")


def make_code_task():
    """Big code dump vs retrieved slices; ask what one function returns."""
    rng = random.Random(31337)
    verbs = ["load", "sync", "merge", "flush", "check", "encode", "route"]
    nouns = ["ledger", "cache", "queue", "bundle", "cursor", "shard", "packet"]
    funcs, used = [], set()
    target_name, gold = None, None
    for i in range(56):
        fname = f"{rng.choice(verbs)}_{rng.choice(nouns)}_{i:02d}"
        while True:
            const = f"menu-item-{rng.randint(100000, 999999)}"
            if const not in used:
                used.add(const)
                break
        src = (f"def {fname}(payload, options=None):\n"
               f'    """{_prose(rng, 40)} {_prose(rng, 30)}"""\n'
               f"    state = prepare(payload, options)\n"
               f"    for item in state.items():\n"
               f"        emit(item)\n"
               f'    return "{const}"\n')
        funcs.append((fname, src))
        if i == 33:
            target_name, gold = fname, const
    dump = "\n\n".join(src for _, src in funcs)
    q = (f"In the code above, what exact string does the function {target_name} "
         f"return? Reply with only that string.")
    sysmsg = {"role": "system",
              "content": "You answer questions using the provided source code."}
    baseline = [sysmsg, {"role": "user", "content": dump + "\n\n" + q}]
    idx = build_text_index({f"{n}.py": s2 for n, s2 in funcs})
    r = retrieve_text(idx, f"function {target_name} return value",
                      token_budget=600, k=4, rerank=False)
    treatment = [sysmsg, {"role": "user", "content": r["context"] + "\n\n" + q}]
    return Task("code_context_qa", baseline, treatment,
                lambda text: gold in text, gold)


def make_tasks():
    return [make_longdoc_task(), make_agent_turn_task(), make_code_task()]


# ------------------------------------------------------------------- RUNNER
def run_provider(provider, budget, tasks):
    """Runs baseline+treatment for each task under the hard cost cap.
    Returns {"rows", "stopped_early", "spent", "calls"} (also printed)."""
    print(f"\n===== provider={provider.name}  model={budget.model} =====")
    wc = budget.worst_case_call_cost()
    print(f"[guard] cap=${budget.cap:.2f}  worst-case/call=${wc:.4f}  "
          f"max_input={MAX_INPUT_TOK} tok  max_output={MAX_OUTPUT_TOK} tok")
    rows, stopped = [], False
    for t in tasks:
        rec = {"task": t.name}
        for arm, msgs in (("baseline", t.baseline_messages),
                          ("treatment", t.treatment_messages)):
            if not budget.can_afford_next_call():
                print(f"[guard] STOP before {t.name}/{arm}: spent "
                      f"${budget.spent:.2f} + worst-case ${wc:.4f} would "
                      f"exceed cap ${budget.cap:.2f}")
                stopped = True
                break
            sent = fit_input_cap(msgs)
            try:
                text, usage = provider.call(sent)
            except Exception as e:
                print(f"[error] {t.name}/{arm}: {type(e).__name__}: "
                      f"{str(e)[:200]}")
                print("[guard] stopping this provider (fail-safe with money)")
                stopped = True
                break
            cost = budget.add(usage)
            print(f"    [{arm}] out={usage['output_tokens']}tok "
                  f"stop={usage.get('stop')!r} correct={bool(t.verify(text))} "
                  f"answer={text[:160]!r}")
            rec[arm] = {"in": usage["input_tokens"],
                        "cached": usage["cached_input_tokens"],
                        "out": usage["output_tokens"],
                        "cost": cost,
                        "correct": bool(t.verify(text)),
                        "stop": usage.get("stop"),
                        "answer": text[:200]}
        if stopped:
            break
        rows.append(rec)
    _summarize(provider, budget, tasks, rows, stopped)
    return {"rows": rows, "stopped_early": stopped,
            "spent": budget.spent, "calls": budget.calls}


def _summarize(provider, budget, tasks, rows, stopped):
    print(f"\n--- summary: {provider.name} ({budget.model}) ---")
    done = [r for r in rows if "baseline" in r and "treatment" in r]
    print(f"tasks completed: {len(done)}/{len(tasks)}"
          + ("  (STOPPED EARLY: hard cost cap)" if stopped else ""))
    tb = tt = cb = ct = 0.0
    okb = okt = 0
    for r in done:
        b, t = r["baseline"], r["treatment"]
        red = 100.0 * (1 - t["in"] / b["in"]) if b["in"] else 0.0
        print(f"  {r['task']:<20} input {b['in']:>6} -> {t['in']:>6} tok "
              f"({red:5.1f}% less)  out {b['out']}/{t['out']}  "
              f"cost ${b['cost']:.4f} -> ${t['cost']:.4f}  "
              f"correct base={b['correct']} treat={t['correct']}")
        tb += b["in"]; tt += t["in"]; cb += b["cost"]; ct += t["cost"]
        okb += b["correct"]; okt += t["correct"]
    if done:
        red = 100.0 * (1 - tt / tb) if tb else 0.0
        saved = cb - ct
        print(f"  TOTAL input tokens: {int(tb)} -> {int(tt)}  ({red:.1f}% reduction)")
        print(f"  $ spent: baseline-arm ${cb:.4f} vs treatment-arm ${ct:.4f}"
              f"  -> saved ${saved:.4f} ({(100 * saved / cb) if cb else 0:.1f}%)")
        print(f"  projected savings at scale: ${saved / len(done) * 10000:,.2f} "
              f"per 10,000 such requests")
        verdict = "PASS (non-inferior)" if okt >= okb else "CHECK (treatment worse)"
        print(f"  quality: baseline {okb}/{len(done)} correct, "
              f"treatment {okt}/{len(done)} correct -> {verdict}")
    print(f"BUDGET: spent ${budget.spent:.2f} of ${budget.cap:.2f} cap "
          f"(under $2 target)")


def main():
    print("heavy_bench: baseline vs TRL-treatment on heavy tasks, hard cost cap")
    print("building deterministic heavy tasks (offline)...", flush=True)
    tasks = make_tasks()
    for t in tasks:
        bt = sum(count_tokens(m.get("content") or "") for m in t.baseline_messages)
        tt = sum(count_tokens(m.get("content") or "") for m in t.treatment_messages)
        print(f"  {t.name:<20} baseline~{bt} tok  treatment~{tt} tok  "
              f"gold={t.gold_desc}")
    ran = 0
    if os.environ.get("OPENAI_API_KEY"):
        model = os.environ.get("OPENAI_MODEL", DEFAULT_MODEL["openai"])
        run_provider(OpenAIProvider(model), Budget("openai", model), tasks)
        ran += 1
    else:
        print("\n[skip] OPENAI_API_KEY not set -> skipping OpenAI")
    if os.environ.get("ANTHROPIC_API_KEY"):
        model = os.environ.get("ANTHROPIC_MODEL", DEFAULT_MODEL["anthropic"])
        run_provider(AnthropicProvider(model), Budget("anthropic", model), tasks)
        ran += 1
    else:
        print("\n[skip] ANTHROPIC_API_KEY not set -> skipping Anthropic")
    if not ran:
        print("\nNo provider keys found; nothing was called (and no money spent).")
    print("\n===== DONE =====")


if __name__ == "__main__":
    main()
