# Contributing

Thanks for looking at the Token-Reduction Layer. The guiding rule for every change:
**remove what the model doesn't need; never what it does — and prove it with a benchmark.**

## Dev setup
```bash
git clone https://github.com/AryanGonsalves/trl-token-reduction
cd trl-token-reduction
pip install -e ".[all,dev]"
python -m pytest -q            # all tests, offline, no keys needed
```

## Before you open a PR
- `python -m pytest -q` is green.
- If you touch a lever, run its benchmark (`python bench/retrieval_bench.py`,
  `bench/cascade_bench.py`, `bench/pipeline_bench.py`) and paste the numbers.
- New quality claims need a non-inferiority test, not an adjective.
- Never commit secrets. `*.bat`, `.env`, and `*_result.txt` are git-ignored for a
  reason — keep keys out of tracked files.

## Layout
- `trl/` — the engine (cache, compress+guard, cascade) and `trl/retrieval/`.
- `proxy/` — OpenAI/Anthropic-compatible proxy + `/compress` endpoint.
- `plugin/` — MCP server + CLI (Claude Code and Codex configs).
- `extension/` — the Claude.ai composer-compression browser extension.
- `bench/` — benchmarks and the honest accounting/stats.
- `tests/` — offline unit tests.
