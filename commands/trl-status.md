---
description: Show what the token-reduction layer is saving this session.
---

Report the token savings from TRL.

- If the local proxy is running (full stack), read its response headers
  `X-TRL-Tokens-Saved` / `X-TRL-Tokens-Before` / `X-TRL-Tokens-After` for the per-request
  reduction (caching + compression + retrieval).
- Otherwise (plugin / retrieval tier), demonstrate the retrieval saving directly: call
  **`retrieve_code`** with a real question about this repo, note the slice tokens it returns,
  and compare against the size of the whole file(s) those slices came from — that difference
  is the retrieval saving. Do **not** run `python -m plugin.cli` from the project folder (the
  `plugin` module isn't importable there); use the `retrieve_code` tool.
- If `TRL_SAVINGS_LOG` is set, every `retrieve_code` call is logged with its slice-vs-whole-file
  saving, and the cumulative total is summed by `validate/savings_report.py` in the TRL repo.

Honest framing: the in-agent plugin delivers the RETRIEVAL tier, not the full proxy-path headline.
