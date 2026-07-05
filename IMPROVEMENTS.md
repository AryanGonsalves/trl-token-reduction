# TRL — Improvements Backlog

Living doc from the Phase-2 quality pass (offline audit + test-driven bug fixing).
Test baseline: **129 passing** (`python -m pytest tests/`). The 128 from Phase 1
plus one new `test_whitespace_only_confident_escalates`.

---

## Fixed this pass

All seven bugs surfaced by the Phase-1 test suite are fixed, and the tests that
asserted the buggy behavior were flipped to assert the corrected behavior.

1. **cascade — empty/blank answer false-accept** (`trl/cascade.py`).
   A confident local answer of `""` (or whitespace) was accepted as final. A blank
   is a local-pipeline failure, so it now escalates to the big model. Added
   `and ans.strip()` to the accept check. Tests: `test_empty_string_confident_escalates`,
   `test_whitespace_only_confident_escalates`.

2. **compress — all-boilerplate tail blanked the message** (`trl/compress.py`).
   When the whole compressible tail was boilerplate, `heuristic_compress` returned
   `""` and the post-heuristic guard only checked length, not emptiness — so the
   folded message ended up with empty content. Now: if the heuristic can't produce
   non-blank output, `compress_request` declines to compress and returns the
   original messages untouched. Test: `test_all_boilerplate_keeps_message_nonblank`.

3. **local_model — traceback `File "..."` frames never matched** (`trl/local_model.py`).
   `_BOILERPLATE` held `'  File "'` (leading spaces) but `_is_boilerplate` runs on a
   stripped line, so the marker could never match. Changed to `'File "'`. Test:
   `test_heuristic_traceback_file_lines_stripped`.

4. **local_model — `summarize` could blank out** (`trl/local_model.py`).
   Docstring promises "never blank out," but the provider-none path returned
   `heuristic_compress` directly, which is `""` on all-boilerplate input. Wrapped
   `summarize` so it returns the original text if compression would blank it.
   Test: `test_summarize_never_blanks_on_all_boilerplate`.

5. **util — `load_config` raised on a missing file** (`trl/util.py`).
   Now returns `{}` (sane default) instead of `FileNotFoundError`. Test:
   `test_load_config_missing_file_returns_empty`.

6. **util — `key: []` parsed to the string `"[]"`** (`trl/util.py`).
   `_scalar` now maps `[]`/`{}` to an empty list/dict, matching `yaml.safe_load`
   so `cfg["exts"] or default` behaves the same on the no-pyyaml path. Test:
   `test_tiny_yaml_empty_list_value_is_empty_list`.

7. **util — mid-value `#` truncated the value** (`trl/util.py`).
   Real YAML only starts a comment at line-start or after whitespace. Added
   `_strip_comment` so a `#` inside a value (e.g. a URL fragment) is kept. Test:
   `test_tiny_yaml_hash_inside_value_is_kept`.

Plus one cosmetic fix folded in: `_preserve_facts("val 42", "")` no longer
prepends a blank line (`test_preserve_into_empty_compressed`).

---

## Newly found — prioritized (not yet changed; awaiting sign-off)

These came out of the audit. None break tests today; several are behavior changes
worth a decision before touching, per the "don't break public API / check in"
guardrail.

### P1 — config lever silently does nothing

- **`compress_history` / `compress_tool_outputs` flags are not selectively wired**
  (`trl/engine.py`). The engine reads both flags but only uses them as
  `if self.compress_history or self.compress_tool_outputs:` to decide whether to
  call `compress_request` at all. `compress_request` then compresses BOTH
  `HISTORY` and `TOOL_RESULT` unconditionally. Setting `compress_history: false`
  while keeping tool-output compression on has no effect — history is still
  compressed. Fix: pass the enabled kinds into `compress_request` and filter on
  them, or split into two calls. Needs a test asserting each flag independently.

### P2 — quality / accounting correctness

- **`meta["local_model_used"]` is wrong for the mock provider** (`trl/engine.py`).
  It reports `self.local.available()`, which is only True for `provider == "ollama"`.
  With `provider == "mock"` the `smart_compress` stand-in DOES run, but meta says
  the local model wasn't used — misleading for accounting/debugging. Report which
  path actually ran instead.

- **`_is_boilerplate` "at " prefix over-matches prose** (`trl/local_model.py`).
  The `"at "` marker strips any stripped line starting with "at " — including real
  content like "at the meeting we decided X". In `heuristic_compress` this can drop
  load-bearing lines. Tighten the marker (e.g. require the stack-frame shape
  `at <ident>(...)`), or scope it to lines that also look like a trace.

- **Rerank mode never applies the `sc <= 0` relevance cutoff** (`trl/retrieval/retrieve.py`).
  Keyword-only mode stops adding symbols once score `<= 0`. In rerank mode the loop
  tests the *blended* score `sc/kw_max + 0.6*cos01`, which is always `> 0` (the
  embedding term is non-negative), so up to `k` symbols are pulled in even when
  nothing keyword-matches — noise for vague/irrelevant queries. Consider gating
  expansion/inclusion on the underlying keyword score, or a blended-score floor.

### P3 — minor / cosmetic / reporting

- **First picked symbol can exceed `token_budget`** (`trl/retrieval/retrieve.py`).
  The budget check is `if used + t > token_budget and chosen:` — the first symbol
  is always added, so one huge symbol silently blows the budget. Intentional
  ("always return something"), but undocumented; consider a hard cap or a note.

- **Folded compressed message drops `key_facts` and blends kinds** (`trl/compress.py`).
  `compress_request` builds `Message(keep.role, keep.kind, new_blob, [])` — it
  discards `key_facts` and reuses the first compressible message's role/kind for a
  blob that may mix HISTORY and TOOL_RESULT. Low impact (key_facts is eval-only
  metadata) but `copy_with` exists for exactly this.

- **`tokens_removed` ignores prefix-cache savings** (`trl/engine.py`).
  `meta["tokens_removed"]` is compression-only (before/after content tokens). When
  caching is the dominant lever, reported savings understate the real win. Consider
  a separate `cache_prefix_tokens` line in the savings summary.

---

## Notes

- Env: this pass ran offline in the sandbox. Reproduce the green baseline with
  `pip install tree_sitter tree_sitter_python tree_sitter_javascript
  tree_sitter_typescript tree_sitter_go tree_sitter_rust tree_sitter_java
  tree_sitter_c_sharp pathspec pyyaml` then `python -m pytest tests/`.
  Without the tree-sitter grammars, the retrieval/AST tests fail on missing
  deps (not real regressions).
- No public API touched: `retrieve`/`build_index` signatures, `Engine.process`,
  `/compress` + proxy shapes, and the `trl-proxy`/`trl-retrieve`/`trl-cli`
  entry points are unchanged.
