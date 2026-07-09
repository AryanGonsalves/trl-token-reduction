# TRL — Improvements Backlog

Living doc from the Phase-2 quality pass (offline audit + test-driven bug fixing).
Test baseline: **139 passing** (`python -m pytest tests/`). The 128 from Phase 1
plus new tests: `test_whitespace_only_confident_escalates`,
`test_only_history_compressed`, `test_only_tool_outputs_compressed`.

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

8. **engine — `compress_history` / `compress_tool_outputs` now act independently**
   (`trl/engine.py`, `trl/compress.py`). Was P1 below. The engine now derives the
   set of eligible message kinds from the two flags and passes it to
   `compress_request(..., kinds=...)` (new optional, backward-compatible param
   defaulting to all `COMPRESSIBLE_KINDS`). Setting `compress_history: false` now
   leaves history untouched while still compressing tool outputs, and vice versa.
   Tests: `test_only_history_compressed`, `test_only_tool_outputs_compressed`.

---

## Fixed in follow-up pass (P2 + P3)

Done and covered by new tests. Note the one caveat at the end.

### P2

- **`meta["local_model_used"]` now accurate + provider surfaced** (`trl/engine.py`,
  `trl/local_model.py`). Added `LocalModel.model_backed()`: True for the mock
  stand-in, a configured OpenAI compressor, or a reachable Ollama; False for
  provider `none`. Engine reports it plus `meta["local_model_provider"]`.
  Tests: `test_local_model_used_true_for_mock`, `test_local_model_used_false_for_none`.

- **`_is_boilerplate` "at " over-match tightened** (`trl/local_model.py`). Replaced
  the bare `"at "` prefix with a `_STACK_FRAME` regex that matches real java/python
  frames (`at a.b.C(...)`, `at java.lang.Thread.run`) but leaves prose ("at the
  meeting we decided X") alone. Tests: `test_is_boilerplate_prose_at_kept`,
  `test_heuristic_keeps_prose_starting_with_at`.

- **Rerank relevance cutoff added** (`trl/retrieval/retrieve.py`). Inclusion now
  carries an `admissible` flag: keyword hits (`score > 0`) always qualify; in
  rerank mode a symbol can also qualify on raw cosine `>= min_similarity` (new
  trailing param, default `0.10`). An unrelated query no longer fills `k` slots
  with near-orthogonal noise. Keyword-only behavior is unchanged. Tests:
  `test_rerank_rejects_unrelated_query`, `test_min_similarity_threshold_tunable`
  (and the existing `test_rerank` still passes — zero-keyword semantic matches
  still surface).
  **Caveat:** `min_similarity=0.10` is a conservative default chosen offline. It
  only rejects near-orthogonal picks and never filters keyword hits, but the exact
  value should be validated against a REAL embedder (bigcode_bench with rerank)
  before trusting it for recall — unlike the pure correctness fixes, this one
  touches retrieval quality.

### P3

- **First-slice-over-budget documented** (`trl/retrieval/retrieve.py`). Added a
  comment at the budget loop explaining the top slice is always emitted (never
  return empty context), so `tokens` can exceed `token_budget` by that one slice.
  Behavior unchanged (already asserted by `test_token_budget_respected`).

- **Folded message preserves `key_facts`** (`trl/compress.py`). `compress_request`
  now unions `key_facts` from every folded message (dedup, order-stable) instead
  of dropping them. Test: `test_folded_message_preserves_key_facts`.

- **`cache_prefix_tokens` surfaced in meta** (`trl/engine.py`). Added
  `meta["cache_prefix_tokens"]` so the caching saving is visible alongside
  compression's `tokens_removed`. Test: `test_cache_prefix_tokens_in_meta`.

---

## Notes

- Env: this pass ran offline in the sandbox. Reproduce the green baseline with
  `pip install tree_sitter tree_sitter_python tree_sitter_javascript
  tree_sitter_typescript tree_sitter_go tree_sitter_rust tree_sitter_java
  tree_sitter_c_sharp pathspec pyyaml` then `python -m pytest tests/`.
  Without the tree-sitter grammars, the retrieval/AST tests fail on missing
  deps (not real regressions).
- Public API backward-compatible: `retrieve` gained a trailing
  `min_similarity=0.10` kwarg (all existing positional/keyword callers unaffected);
  `compress_request` gained a trailing `kinds=` kwarg. `build_index` signature, `Engine.process`,
  `/compress` + proxy shapes, and the `trl-proxy`/`trl-retrieve`/`trl-cli`
  entry points are unchanged.

---

## Install UX backlog (from the live Claude Code + Roblox dogfood)

**Verdict:** auto-targeting is genuinely one-and-done (CLAUDE_PROJECT_DIR resolves the project,
no config) — but INSTALL is NOT "simple one-time." A real user hit: SSH-clone failure (needs
HTTPS URL), Python deps missing (venv OR `pip install --user`), "which interpreter does Claude
Code use" fragility (MCP server failed on relaunch until deps were in the SYSTEM python too),
`/reload-plugins` required, plugin got toggled Disabled, version bump needed for `Update now`.

**Root cause:** any plugin that makes the user pip-install into the right interpreter cannot be
one-click. Fix directions (do these to make it real one-time):
1. **Bundle deps** — vendor the pure-python deps + tree-sitter wheels inside the plugin so no
   pip step is needed (the MCP server adds the vendored dir to sys.path).
2. **First-run bootstrap** — on first server start, auto `pip install` the missing deps into the
   running interpreter (guarded, idempotent), or ship a one-shot `trl-plugin-setup` script.
3. **Self-contained runtime** — freeze the server (PyInstaller / zipapp `.pyz`) and point the
   `.mcp.json` `command` at the bundled binary, so no interpreter/deps selection at all.
4. **Interpreter pin/auto-detect** — resolve a known-good python (or the venv) in the server
   launch instead of bare `python`, to kill the relaunch fragility.
5. Docs: SETUP.md already covers venv + HTTPS + `--user`; keep it as the interim path.

**Tool robustness (done):** `retrieve_code`/`explain_symbol` now accept common param aliases
(`k`, `token_budget`, `limit`, `path`, `project`) and soft-require query/name (self-correcting
hint instead of "Invalid tool parameters"). Fixes silent retrieval-call failures seen in the dogfood.
