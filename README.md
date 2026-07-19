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

**Independent out-of-distribution check.** Pointed the retriever at a *separate
~52k-token production Python codebase it had never seen* (35 files, 359 symbols) and ran
8 natural-language audit queries. Retrieval returned ~1k tokens of slices per query vs the
52k whole-dump — **~98% fewer** — with the answer-bearing module/symbol as the top hit on
descriptively-named queries. (Informal relevance check, not a labeled precision eval; point
it at your own repo: `python -m validate.measure_repo_reduction --repo <path>`.)

**Real-world longitudinal usage — an entire game built with the plugin (live, logged).**
Beyond the offline/API benchmarks, the plugin was dogfooded across a *full project*: a Roblox
game ("Hoard") built with Claude Code over ~11 sessions (10 feature phases + a verify/harden
pass), from an empty scaffold to a 28-file / ~38k-token codebase. Two independent things were
measured at every phase — the **direct** retrieval reduction on the repo, and the plugin's **own
live savings log** (`TRL_SAVINGS_LOG`): exactly what the agent called and what each returned slice
replaced.

| Hoard (Luau/Roblox), tracked as the repo grew | Result |
|---|---|
| **Direct** reduction vs whole-repo dump | **52% -> 98%** as the repo scaled ~2.2k -> ~38k tokens (10/10 relevant top-hits on descriptive queries) |
| **Live** agent usage (the plugin's savings log) | **84 real calls, 602,659 tokens saved, 90.9% fewer** vs the file(s) those slices would otherwise have been read from |

The live curve climbed with the codebase (85% -> 91% cumulative across phases) toward the ~98%
per-call direct ceiling — i.e. the bigger the project got, the more a ~few-hundred-token slice beat
reading whole files. Honest caveats, stated plainly: (1) the live "counterfactual" is the whole
*file(s)* each slice came from — what the agent would otherwise read — not the whole repo, so it's a
realistic per-call baseline, not a favorable one; (2) savings only accrue on **adoption** —
feature-*creation* phases call retrieval little, integration/refactor/hardening phases call it heavily
(where it pays most), so the cumulative number reflects real mixed usage; (3) scope is one project,
one developer, one language, and two early phases' calls were **lost to a logging bug before it was
fixed** (disclosed and excluded) — so the 84 calls are the reliably-logged subset and the true total
was higher. Reproduce on your own project: `python -m validate.measure_repo_reduction --repo <path>`
(direct) and set `TRL_SAVINGS_LOG`, then `python -m validate.savings_report <log>` (live).

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
CODEBASE-AWARE surface (library / MCP plugin / agent integration — can see your repo):
  request ──► retrieve (AST slices, local)     # lever 3: don't stuff whole files
          ──► cascade  (easy → local, $0)       # lever 4: needs a local model
          ──► Engine.process:
                ├─ cache-mark stable prefix      # lever 1
                └─ compress tail + fact guard    # lever 2
          ──► big model (only when needed)

BLIND proxy (base_url swap — CANNOT see your repo):
  request ──► Engine.process: cache-mark prefix + compress tail + fact guard   # levers 1 & 2
          ──► retrieve ONLY over context you pass in a `documents` field       # lever 3, opt-in
          ──► big model
  (cascade and codebase-wide retrieval are NOT available on the blind proxy)
```

### Which lever lives on which surface

The headline retrieval numbers (95.7% cross-file, and the ~87% frontier runs) come
from the RETRIEVAL-heavy code-agent regime, which needs a surface that can **index
your codebase**. The blind proxy can't see your repo, so on the proxy only caching +
compression fire automatically. **Never read the 87%/95.7% as a blind-proxy number.**

| Surface | caching (1) | compression + guard (2) | retrieval (3) | cascade (4) |
|---|---|---|---|---|
| **Blind proxy** (base_url swap) | ✓ auto | ✓ auto | only over a `documents` field you pass | ✗ |
| **Library / Engine** (in your agent) | ✓ | ✓ | ✓ indexes your repo | ✓ if local model |
| **MCP plugin** (Claude Code / Codex) | ✓ | ✓ | ✓ | ✓ if local model |
| **Browser extension** (`/compress`) | — | ✓ | ✓ (text) | ✗ |

The full-stack ~99% offline reduction over this repo (`validate/integrated_loop.py`)
is a *codebase-aware* run — retrieval doing most of the work, compression + caching
stacking on top. The blind proxy delivers the compression + caching portion only
(the single-lever live-proxy rows above: ~56–68% on a bloated turn).

- `trl/` — the shared engine (caching, compression+guard, cascade router) and
  `trl/retrieval/` (tree-sitter extractor + retriever, **13 languages / 20 file
  types**: Python, JS/JSX, TS/TSX, Go, Rust, Java, C#, C, C++, Ruby, PHP, Kotlin, Luau/Roblox),
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

**Who benefits (be honest):** anyone paying **metered API** per token (pay-as-you-go),
and anyone on a **token-metered subscription** — Claude Code (a flat monthly fee, but
usage is *metered in tokens* against your weekly caps) and Codex (which OpenAI moved to
token-based pricing in Apr 2026). On a subscription this doesn't cut a bill — it makes
you burn your quota slower, so you hit the weekly/5-hour caps later (more work per plan).
It does **not** help the ChatGPT/Claude *chat websites* (closed endpoints; ChatGPT's cap
is per-message, not per-token).

## How you use it

Four ways to put it in front of your model — pick by how much you want to change.

### 1. Drop-in proxy (any app, zero code changes)
The proxy speaks both the OpenAI **and** Anthropic wire formats. Point your
client's `base_url` at it; keep your own key (the proxy never stores it). Every
request gets **caching + compression (+ fact guard)** applied on the way through,
and comes back with an `X-TRL-Tokens-Saved` header so you can see the cut per call.
(The blind proxy can't see your codebase, so the retrieval and cascade levers live
on the codebase-aware surfaces below — see the surface/lever table above.)

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
from trl.util import loa
## Claude Code plugin (retrieval tier)

The repo doubles as a Claude Code plugin **and** its own marketplace — no store, no
review, just files. Add the marketplace (`AryanGonsalves/trl-token-reduction`) and
install the `trl` plugin. It ships:

- the `trl-retrieve` **MCP server** (`retrieve_code`, `explain_symbol`) — the agent
  pulls exact AST slices instead of reading whole files;
- a **skill** that tells the agent to actually use those tools;
- `/trl-index` (build/refresh the index) and `/trl-status` (show savings).

It auto-targets YOUR project at runtime (`$TRL_REPO` / `$CLAUDE_PROJECT_DIR` / nearest `.git` / cwd) and caches the index at `<project>/.trl/index.json`; if it can't resolve the project it asks you to run `/trl-index` or set `TRL_REPO`.

**Honest scope:** the plugin delivers the **retrieval tier** — cutting context tokens by
fetching slices, not whole files. It does **not** deliver the full proxy-path headline
(~87%); prefix caching + tail compression require running the local proxy and pointing
your agent's base URL at it (two-tier note above).

### Optional hosted rerank (precision, off by default)

For vague natural-language questions where keyword retrieval misses the right symbol,
`retrieve(rerank="hosted")` asks a hosted model (your own `ANTHROPIC_API_KEY`,
`claude-haiku-4-5-20251001` by default) to reorder the shortlist. Validated on a
15-query NL set (2 runs): free `doc_boost` **6/15** → Haiku **11/15**, Sonnet
**8.5/15** (oracle ceiling **12/15**), with the 6/6 code loop non-inferior. It is a
**precision option, not a token saver** — ~1¢/query via Haiku on your own key — and is
**off by default**. The remaining 11→12 gap is retrieval-recall/shortlist coverage, not
the reranker.
