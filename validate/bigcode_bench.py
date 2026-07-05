"""Large / multi-file codebase benchmark: CROSS-FILE tasks answered from the
WHOLE codebase (baseline) vs TRL retrieval-reduced context (treatment), on
GPT-5.5 / Claude Opus 4.8, with a HARD cost cap.

This directly tests the regime a commenter flagged: "on larger codebases you need
a lot of context for consistency." Each task's correct answer requires tracing
across >=2 files. Baseline sends the entire codebase (~30k tokens); treatment
sends only what the AST retriever pulls for the question. We measure whether the
reduced context still answers the cross-file question (non-inferiority) and the
billed-token reduction.

Reuses heavy_bench's VERIFIED cost guard + providers; only the input cap is
raised (and the guard's worst-case is raised in lockstep, so it stays correct).

Run: OPENAI_API_KEY=... ANTHROPIC_API_KEY=... python -u validate/bigcode_bench.py
Env: OPENAI_MODEL (default gpt-5.5), ANTHROPIC_MODEL (default claude-opus-4-8),
     REPO_DIR (default = this repo).
Offline proof: tests/test_bigcode_bench_offline.py
"""
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

import validate.heavy_bench as hb
from validate.heavy_bench import (Budget, OpenAIProvider, AnthropicProvider,
                                  fit_input_cap, DEFAULT_MODEL)

# Larger context so the whole ~30k-token codebase fits as a true full-context
# baseline. We do NOT mutate heavy_bench's globals (that would corrupt its own
# tests); instead BigBudget overrides the guard's worst-case for this cap.
BIG_MAX_INPUT = 34000
BIG_MAX_OUTPUT = 1000   # reasoning models (gpt-5.x) burn output on hidden reasoning;
                        # 300 was too low and produced empty stop='length' answers.
# Anthropic bills ~1.6x more tokens than tiktoken counts, so inflate its input
# estimate to keep the hard cost cap honest (never underestimates real spend).
_TOK_FACTOR = {"openai": 1.0, "anthropic": 1.6}


class BigBudget(Budget):
    """Same hard cost guard, but worst-case reflects this benchmark's larger
    input/output caps AND each provider's tokenizer inflation, so the cap can
    never underestimate a call's real cost."""
    def worst_case_call_cost(self):
        p = self.prices
        f = _TOK_FACTOR.get(self.provider, 1.6)
        return (BIG_MAX_INPUT * f * p["in"] + BIG_MAX_OUTPUT * p["out"]) / 1e6
from trl.util import count_tokens
from trl.retrieval import build_index, retrieve

REPO_DIR = os.environ.get("REPO_DIR", ROOT)
CODE_DIRS = ["trl", "proxy", "plugin", "bench"]


def _all_py(root):
    files = []
    bases = [os.path.join(root, d) for d in CODE_DIRS
             if os.path.isdir(os.path.join(root, d))] or [root]
    for base in bases:
        for r, _, fs in os.walk(base):
            if "__pycache__" in r:
                continue
            for f in fs:
                if f.endswith(".py"):
                    files.append(os.path.join(r, f))
    return sorted(set(files))


def whole_codebase_text(root):
    parts = []
    for f in _all_py(root):
        try:
            src = open(f, encoding="utf-8", errors="ignore").read()
        except Exception:
            continue
        parts.append(f"# ===== FILE: {os.path.relpath(f, root)} =====\n{src}")
    return "\n\n".join(parts)


class Task:
    def __init__(self, name, question, gold, retr_query):
        self.name = name
        self.question = question
        self.gold = gold            # ALL of these must appear in the answer
        self.retr_query = retr_query

    def verify(self, text):
        t = (text or "").lower()
        return all(g.lower() in t for g in self.gold)


# Cross-file tasks (gold verified against the real code; each spans >=2 files).
TASKS = [
    Task("docs_flow__proxy_to_retrieval",
         "When a chat request carries a non-standard 'documents' field, trace how "
         "it's handled: (a) which function applies the document retrieval, (b) which "
         "retrieval function does it call, and (c) as what message role is the "
         "retrieved context inserted? Name the two functions and the role.",
         ["_apply_document_retrieval", "retrieve_text", "system"],
         "documents field retrieval injected into chat request messages as system"),
    Task("factguard__engine_to_compress",
         "The engine compresses the conversation tail, and a guard prevents numbers "
         "from being lost. (a) which function does the engine call to compress the "
         "tail, and (b) which function re-injects any number the compressor dropped? "
         "Name both functions.",
         ["compress_request", "_preserve_facts"],
         "engine compress conversation tail guard re-inject dropped numbers"),
    Task("stable_prefix__engine_to_cache",
         "How does the engine mark the cacheable stable prefix? (a) which Engine "
         "method runs the pipeline, (b) which function computes the stable prefix, "
         "and (c) which module/file is that function defined in? Name the method, the "
         "function, and the file.",
         ["process", "stable_prefix", "cache"],
         "engine method stable prefix caching computed in which module"),
]

SYS = {"role": "system",
       "content": "You are a senior engineer answering questions about the "
                  "provided codebase. Be concise and name the exact "
                  "function/file identifiers involved."}


def build_arms(root):
    whole = whole_codebase_text(root)
    idx = build_index(root)
    arms = []
    for t in TASKS:
        baseline = [SYS, {"role": "user",
                          "content": whole + "\n\nQUESTION: " + t.question}]
        r = retrieve(idx, t.retr_query, token_budget=1500, k=10)
        treatment = [SYS, {"role": "user",
                           "content": (r.get("context", "") or "") +
                                      "\n\nQUESTION: " + t.question}]
        arms.append((t, baseline, treatment))
    return arms, whole


def run_provider(provider, budget, arms):
    print(f"\n===== provider={provider.name}  model={budget.model} =====", flush=True)
    wc = budget.worst_case_call_cost()
    print(f"[guard] cap=${budget.cap:.2f}  worst-case/call=${wc:.4f}  "
          f"max_input={BIG_MAX_INPUT}  max_output={BIG_MAX_OUTPUT}", flush=True)
    rows, stopped = [], False
    for t, baseline, treatment in arms:
        rec = {"task": t.name}
        for arm, msgs in (("baseline", baseline), ("treatment", treatment)):
            if not budget.can_afford_next_call():
                print(f"[guard] STOP before {t.name}/{arm}: spent ${budget.spent:.2f} "
                      f"+ worst-case ${wc:.4f} would exceed cap", flush=True)
                stopped = True
                break
            sent = fit_input_cap(msgs, cap=BIG_MAX_INPUT)
            try:
                text, usage = provider.call(sent)
            except Exception as e:
                print(f"[error] {t.name}/{arm}: {type(e).__name__}: {str(e)[:200]}", flush=True)
                print("[guard] stopping this provider (fail-safe with money)", flush=True)
                stopped = True
                break
            budget.add(usage)
            ok = t.verify(text)
            rec[arm] = {"in": usage["input_tokens"], "out": usage["output_tokens"],
                        "stop": usage.get("stop"), "correct": ok}
            print(f"    [{arm}] in={usage['input_tokens']} out={usage['output_tokens']} "
                  f"stop={usage.get('stop')!r} correct={ok} ans={ (text or '')[:150]!r}", flush=True)
        if stopped:
            break
        rows.append(rec)
    _summarize(provider, budget, rows, stopped)
    return rows


def _summarize(provider, budget, rows, stopped):
    done = [r for r in rows if "baseline" in r and "treatment" in r]
    print(f"\n--- summary: {provider.name} ({budget.model}) ---", flush=True)
    print(f"tasks completed: {len(done)}/{len(TASKS)}"
          + ("  (STOPPED EARLY: cost cap)" if stopped else ""), flush=True)
    for r in done:
        print(f"  {r['task']:34s} in {r['baseline']['in']:6d} -> {r['treatment']['in']:5d}"
              f"   correct base={r['baseline']['correct']} treat={r['treatment']['correct']}", flush=True)
    bi = sum(r["baseline"]["in"] for r in done)
    ti = sum(r["treatment"]["in"] for r in done)
    bok = sum(r["baseline"]["correct"] for r in done)
    tok = sum(r["treatment"]["correct"] for r in done)
    if bi:
        print(f"  TOTAL input tokens: {bi} -> {ti}  ({100*(1-ti/bi):.1f}% reduction)", flush=True)
    print(f"  cross-file quality: baseline {bok}/{len(done)} correct, "
          f"treatment {tok}/{len(done)} correct", flush=True)
    verdict = ("PASS (non-inferior)" if tok >= bok
               else f"REGRESSION: treatment lost {bok - tok} vs baseline")
    print(f"  VERDICT: {verdict}", flush=True)
    print(f"BUDGET: spent ${budget.spent:.2f} of ${budget.cap:.2f} cap (under $2 target)", flush=True)


def main():
    hb.MAX_OUTPUT_TOK = BIG_MAX_OUTPUT   # run-time only; not at import (test-safe)
    print("bigcode_bench: cross-file codebase QA, full-context vs TRL retrieval, hard cost cap", flush=True)
    print(f"codebase: {REPO_DIR}", flush=True)
    arms, whole = build_arms(REPO_DIR)
    print(f"whole-codebase context ~{count_tokens(whole)} tokens across "
          f"{len(_all_py(REPO_DIR))} files; {len(TASKS)} cross-file tasks", flush=True)
    for t, _, _ in arms:
        miss = [g for g in t.gold if g.lower() not in whole.lower()]
        print(f"  gold-in-codebase {t.name}: "
              f"{'ALL present' if not miss else 'MISSING ' + str(miss)}", flush=True)
    ran = False
    if os.environ.get("OPENAI_API_KEY"):
        m = os.environ.get("OPENAI_MODEL", DEFAULT_MODEL["openai"])
        run_provider(OpenAIProvider(m), BigBudget("openai", m), arms)
        ran = True
    else:
        print("\n[skip] OPENAI_API_KEY not set -> skipping OpenAI", flush=True)
    if os.environ.get("ANTHROPIC_API_KEY"):
        m = os.environ.get("ANTHROPIC_MODEL", DEFAULT_MODEL["anthropic"])
        run_provider(AnthropicProvider(m), BigBudget("anthropic", m), arms)
        ran = True
    else:
        print("\n[skip] ANTHROPIC_API_KEY not set -> skipping Anthropic", flush=True)
    if not ran:
        print("\nno provider keys found; nothing was called (no money spent).", flush=True)
    print("\n===== DONE =====", flush=True)


if __name__ == "__main__":
    main()
