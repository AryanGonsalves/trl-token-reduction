# Token-Reduction Layer for LLM Apps & Agents

A vendor-neutral efficiency layer that sits in front of an expensive API model
(Claude / GPT) and cuts token spend **several-fold with a published,
quality-neutral benchmark** — not a hand-wavy claim. Four composable levers, each
measured against the rule: **remove what the model doesn't need; never what it does.**

> Status: research build. Every lever below is implemented, benchmarked, and
> unit-tested offline. Numbers are from the included benchmarks (see *Reproduce*).
> The engine is real; some big-model arms use mocks/oracles where noted — the
> *structure* and the *quality-neutrality tests* are the contribution.

## Why this exists

Agents are pathologically wasteful: they resend the full system prompt + tool
schemas + entire history every step, dump huge raw tool outputs, and route every
step — routine or hard — to the frontier model. The savings come from removing
that redundancy, irrelevance, and grunt work, **measured** so you know quality
didn't move.

## The four levers (all built, all measured)

| Lever | What it does | Result (benchmark) | Quality |
|-------|--------------|--------------------|---------|
| **Caching** | bill the stable prefix once at the cache rate, not full freight each step | neutral vs a *cache-enabled* baseline (the honest baseline) | — |
| **Compression + guard** | a local model summarizes/dedupes the growing tail; a deterministic guard re-injects any number it drops | ~37% fewer tail tokens | **100%** (guard makes it exact-safe) |
| **Retrieval** | replace whole-file code dumps with only the relevant AST slices (tree-sitter, local, zero API tokens) | **5.9× / 83%** fewer context tokens on code-QA | **100%**, verbatim slices |
| **Cascade** | answer verifiable/easy steps on the cheap local pipeline; escalate only hard steps to the big model | **75% fewer big-model calls** | **100%**, 0 false-accepts |

**Compound (all four, one 20-turn code-agent session):**
`18.1× cheaper · 94.5% less $ · 80% fewer big-model calls · quality 100% = naive.`
The levers *multiply*, not just add.

Honest caveat, stated up front: the compound number is a *favorable* synthetic
workload (cascade handles the verifiable majority). Real agent mixes vary — our
long-standing story is **3–10× on favorable workloads, modest on pure novel
reasoning.** The point of the 18× demo is that the levers stack multiplicatively,
not the exact figure.

## Validated on real APIs (billed tokens, not estimates)

The benchmarks above run offline. But the levers were also proven **end-to-end
against live models**, and every number here is the **provider's own reported
billed token count** (OpenAI `usage.prompt_tokens`; Anthropic `usage.input_tokens`
including cache) — not our estimate, not a mock.

**Flagship models, heavy tasks (the headline result).** Run on the two most advanced
models available, over heavy tasks built from *real* content (the project's own docs
and code, ~6–10k tokens each), baseline vs token-reduced:

| Flagship model | Input tokens | Quality |
|----------------|--------------|---------|
| **OpenAI GPT-5.5** | **16,875 → 2,232 (86.8% fewer)** | **3/3 → 3/3, non-inferior PASS** |
| **Anthropic Claude Opus 4.8** | **26,573 → 3,343 (87.4% fewer)** | **3/3 → 3/3, non-inferior PASS** |

~87% of input tokens removed on the current frontier, with quality fully preserved on
both. (Reproduce: `validate/heavy_bench.py`, hard-capped at $1.80/provider.) The three
tasks are a long-document QA, a bloated agent turn, and a code-context QA.

**Cross-file, multi-file codebase (the "does it hold on a bigger codebase?" test).**
Three questions that each require tracing across 2–3 files, answered from the *whole*
codebase (~30k tokens) vs the retrieval-reduced context, same non-inferiority test:

| Cross-file codebase QA (~30k-token repo) | Input tokens | Quality |
|------------------------------------------|--------------|---------|
| **OpenAI GPT-5.5** | **89,845 → 3,891 (95.7% fewer)** | **3/3 → 3/3, non-inferior PASS** |
| **Anthropic Claude Opus 4.8** | **141,628 → 6,102 (95.7% fewer)** | **3/3 → 3/3, non-inferior PASS** |

On a real multi-file codebase, the retrieval-reduced context answered the cross-file
tracing tasks as well as the full context. Honest scope: this is a ~30k-token repo —
*medium* scale, not a 500k-line monorepo, and n=3 tasks. (Reproduce:
`validate/bigcode_bench.py`, hard-capped at $1.80/provider.)

| Earlier single-lever / mid-tier runs | Reduction | Quality / correctness |
|----------------|-----------|-----------------------|
| Realistic verifier suite — **OpenAI**, safe mode | **2.59× cheaper**, 43.1% fewer input tokens, 62.7% fewer sub-units | 100% → 100%, non-inferiority **PASS** |
| Live proxy, one bloated turn — **OpenAI gpt-4o-mini** | **1,672 → 730** billed input tokens (**56.3% fewer**) | output correct, fact-guard held |
| Compression lever — **OpenAI gpt-4o-mini** | **966 → 305** (**68% fewer**) | correct |
| Document retrieval — **OpenAI gpt-4o-mini** | **1,374 → 318** (**77% fewer**) | correct |
| Cascade — **OpenAI gpt-4o-mini** | **89%** of steps answered locally ($0 to the API) | **100%** accuracy, 0 false-accepts |
| Live proxy, compression + cache — **Anthropic claude-haiku-4.5** | **1,198 → 477** billed input tokens (**60% fewer**) | correct |

Honest caveats, stated plainly: the suites are small, the multi-lever suite is a
*favorable* workload, it's one model per provider, and the live-proxy rows each
isolate a single lever. These are directional — but they are **real billed tokens
on real models through the actual proxy**, which is the bar that matters. Reproduce
them with your own key via `RUN.md` (`validate/live_openai.py`, `validate/live_anthropic.py`).

## What we measured and learned (the honest findings)

- A **cache-enabled baseline** neutralizes the caching lever — the real
  differential comes from the tail (compression + retrieval) and from cascade.
- **A real 3B local model is a lossy compressor**: llama-3.2-3b dropped a
  load-bearing fact ~1 in 3 times on a hard workload. The **fact-preserving
  guard** (re-inject any dropped number, deterministically) restores quality to
  100% while keeping most savings. Compression is only shippable *with* the guard.
- **Text & PDFs get the same treatment**: a separate chunk-based retriever
  slices prose/PDF documents to the passages that matter (numbers preserved for
  disambiguation), so non-code requests cost fewer tokens too — without touching
  the code path.
- **Semantic ranking, tested honestly**: on deliberately vague queries, static
  embeddings gave *no* lift over keyword (dropped); an LLM-reranker is a small,
  real, regression-free gain but costs one cheap model call, so it ships opt-in.
- **For code, retrieval beats compression on both axes** — bigger token cut *and*
  quality-safe by construction (exact slices can't paraphrase a fact away).
- **Subscription limits (Claude Pro/Max) are server-side** — you can't turn a
  subscription into cheap bulk API calls; the OAuth token authenticates but is
  hard rate-limited. The clean, attackable target is metered API $, plus
  *local-side* reduction inside coding-agent clients.

## Architecture

```
request ──► retrieve (AST slices, local)     # lever 3: don't stuff whole files
        ──► cascade  (easy → local, $0)       # lever 4: skip the big model entirely
        ──► Engine.process:
              ├─ cache-mark stable prefix      # lever 1
              └─ compress tail + fact guard    # lever 2
        ──► big model (only when needed)
```

- `trl/` — the shared engine (caching, compression+guard, cascade router) and
  `trl/retrieval/` (tree-sitter extractor + retriever, **12 languages / 18 file
  types**: Python, JS/JSX, TS/TSX, Go, Rust, Java, C#, C, C++, Ruby, PHP, Kotlin),
  plus a general **text + PDF** retriever (`text_index.py`, `pdf.py`) so non-code
  documents get the same slice-don't-dump treatment.
- `bench/` — the harness: baseline (cache-enabled) vs treatment, real token/$
  accounting, **non-inferiority** quality gates, and one benchmark per lever plus
  the compound `pipeline_bench.py`.
- `tests/` — unit tests for every lever and provider parser.

## Install

```bash
pip install trl-token-reduction            # core (stdlib only)
pip install "trl-token-reduction[all]"     # + retrieval grammars, proxy, model SDKs, MCP, PDF
```
Or from source: `git clone … && pip install -e ".[all]"`. Installing exposes three
commands — `trl-proxy`, `trl-retrieve`, `trl-cli` — used below. Extras are modular:
`[retrieval]`, `[proxy]`, `[models]`, `[mcp]`, `[embed]`, `[pdf]`.

**Who benefits (be honest):** anyone paying **metered API** per token, and anyone on a
**token-metered subscription** — Claude Code and (since Apr 2026) Codex, whose caps
shrink as you send fewer tokens. It does **not** discount the ChatGPT/Claude *chat
websites* (closed endpoints; ChatGPT's cap is per-message, not per-token).

## How you use it

Four ways to put it in front of your model — pick by how much you want to change.

### 1. Drop-in proxy (any app, zero code changes)
The proxy speaks both the OpenAI **and** Anthropic wire formats. Point your
client's `base_url` at it; keep your own key (the proxy never stores it). Every
request gets the levers applied on the way through, and comes back with an
`X-TRL-Tokens-Saved` header so you can see the cut per call.

```bash
trl-proxy                              # listens on :8899, forwards upstream
# (or: python -m proxy.server)
```
```python
# OpenAI SDK — the ONLY change is base_url
client = OpenAI(base_url="http://localhost:8899/v1", api_key=YOUR_KEY)
# Anthropic SDK works the same via /v1/messages
```
Want a document shrunk before it hits the model? Add a non-standard
`documents: [...]` field to the request — the proxy retrieves only the relevant
passages and injects them, instead of you pasting the whole file.

### 2. Coding-agent plugin (Claude Code, Codex, or any MCP client)
Installs an MCP server `trl-retrieve` exposing `retrieve_code(query)` and
`explain_symbol(name)`. Your agent asks for *code that answers a question* and
gets AST slices (file:line + source) instead of stuffing whole files. Drop
`plugin/claude-code/.mcp.json` into a repo and point `TRL_REPO` at it. **Codex**
uses the same STDIO server — drop the `[mcp_servers.trl-retrieve]` block from
`plugin/codex/config.toml` into `~/.codex/config.toml`. See `plugin/INSTALL.md`.
No agent? Same thing from the shell:

```bash
trl-cli "how does auth refresh work?" --repo /path/to/repo
# (or: python -m plugin.cli ...)
```

### 3. Library (embed the engine directly)
Call the pieces from your own code when you control the request path:

```python
from trl import Engine
from trl.util import load_config
from trl.retrieval import build_index, retrieve

eng = Engine(load_config("config.yaml"))   # caching + compression + cascade
idx = build_index("/path/to/repo")          # incremental; persists + rebuilds on change
hits = retrieve(idx, "where do we validate tokens?", token_budget=1200)
# hits["context"] -> just the relevant slices, ready to send
```

Retrieval is keyword-based and free by default. For vague, non-literal queries
you can pass an optional `rerank`/LLM-rerank callable — a small paid gain with no
regressions (see the findings below); it's off unless you turn it on.

### 4. Composer extension (stretch a Claude.ai subscription)
For the one surface you can't proxy — the Claude.ai chat box — a browser extension
compresses your *pasted* context before you send it, so you burn fewer tokens against
your subscription bucket. Manual + preview-first (a "numbers preserved" badge shows
the fact-guard at work); nothing sends automatically. Run `trl-proxy` for the local
`/compress` endpoint, load `extension/` unpacked, and click **⚡ Compress** on claude.ai.
See `extension/README.md`. (Helps token-metered Claude; not ChatGPT's per-message cap.)

## Reproduce

```bash
pip install -r requirements.txt
python bench/retrieval_bench.py     # retrieval: 5.9× on code-QA, quality-neutral
python bench/cascade_bench.py       # cascade: 75% fewer big-model calls
python bench/pipeline_bench.py      # compound: all 4 levers, ~18× on a session
python -m pytest -q   # or: for t in tests/test_*.py; do python "$t"; done
```

Real API / local-model arms (need a key or Ollama) are wired too — see `RUN.md`.

## Design principles

Cost is per **token**, not per character. You can't get drastic + lossless +
zero-quality-loss all at once (information theory) — so every lever is judged by a
**published non-inferiority test**, never the unfalsifiable word "zero." The
benchmark *is* the product's credibility.
