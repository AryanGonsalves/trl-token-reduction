# How to run

## Offline (no keys, no GPU) — validates the machinery
```bash
python run_benchmark.py --suite toy --mock                 # smoke test
python run_benchmark.py --suite realistic --mock           # verifier suite
python run_benchmark.py --suite realistic --mock --compression aggressive
python tests/test_providers_shape.py                       # real-arm parsing
```

## Real number (this is the make-or-break) — needs ONE API key + $
```bash
export ANTHROPIC_API_KEY=sk-...        # or OPENAI_API_KEY
# 1) look before you spend: build requests, no network
python run_benchmark.py --suite realistic --provider anthropic --dry-run
# 2) real run (small: 18 tasks x 2 arms = 36 calls, short max_tokens)
python run_benchmark.py --suite realistic --provider anthropic
```
Before quoting dollars: put TODAY's real prices in `config.yaml` (`big_model`
price_* fields). The defaults are placeholders.

## Run on your Claude SUBSCRIPTION (no metered API key)
Uses the local Claude Code CLI on your subscription login. This measures
**subscription usage** (the World-B meter) rather than API dollars.

Requires: Claude Code installed and logged in (`claude` runs interactively OK).
```bash
# 0) confirm the CLI + see the exact usage JSON once (subscription call):
echo "reply with only the integer 3" | claude -p --output-format json
# 1) dry-run (free): builds the commands, no calls
python run_benchmark.py --suite realistic --provider claude-cli --dry-run
# 2) real (consumes your subscription budget; ~36 short calls):
python run_benchmark.py --suite realistic --provider claude-cli
```
Caveats (why this is a local signal, not the published number):
- NOT `--bare` — bare mode needs an API key and skips subscription OAuth. We use
  plain `-p`, replace the system prompt with our stable prefix, and run from a
  clean temp dir so no CLAUDE.md/.mcp.json loads.
- Residual Claude Code scaffold overhead hits BOTH arms equally -> relative
  savings valid, absolute token counts inflated.
- Prefix caching is CC-managed and opaque; `cached_input_tokens` is whatever CC
  reports. Treat sub-usage numbers as directional.
- Windows: if `claude` isn't found, set `claude_cli.bin` in config.yaml to
  `claude.cmd` or the full path.

## Add the real local model (compression quality that actually matters)
```bash
ollama serve & ; ollama pull qwen2.5:7b-instruct
# set local_model.provider: ollama in config.yaml
python tests/test_ollama_smoke.py                          # must PASS (fact kept)
python run_benchmark.py --suite realistic --provider anthropic
```
The mock local model (`smart_compress`) is an OPTIMISTIC stand-in. The real
question is whether qwen reproduces it on real tool outputs. The smoke test
fails loudly if the model drops a load-bearing fact.

## Publish-grade suite
Install tau-bench and implement `bench/tau_bench_adapter.py::load_tau_bench`
(module docstring has the mapping). Then `--suite tau-bench`. Everything else —
accounting, stats, gates — is unchanged.

## Cost control
- `max_tokens=64` per call by design (we score short verifiable answers).
- Suite sizes are small; bump `n_favorable` in the suite files for tighter CIs.
- `--dry-run` estimates token structure for free before any real run.

## Use it as a drop-in proxy (v0 product skin)
Zero code change for the caller — point your OpenAI client's base_url at the proxy;
it applies the levers and forwards upstream with YOUR key.
```bash
python -m proxy.server                     # listens on :8899 -> OpenAI
# then in your client:  base_url = http://localhost:8899/v1   (api key unchanged)
# forward to Anthropic instead:  TRL_UPSTREAM=https://api.anthropic.com python -m proxy.server
```
Each response carries `X-TRL-Tokens-Saved` / `-Before` / `-After` so you can see
the per-request reduction. The transform is unit-tested offline
(`tests/test_proxy_transform.py`); forwarding needs a real key.

## Proxy is vendor-neutral
The proxy handles both OpenAI (`/v1/chat/completions`) and Anthropic (`/v1/messages`)
request shapes (Anthropic gets explicit `cache_control` on the stable prefix), and
streams SSE responses through when `stream: true`.
```bash
python -m proxy.server                                        # -> OpenAI
TRL_UPSTREAM=https://api.anthropic.com python -m proxy.server  # -> Anthropic
```
