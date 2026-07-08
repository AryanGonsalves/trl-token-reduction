---
description: Show what the token-reduction layer is saving this session.
---

Report the token savings from TRL.

- If the local proxy is running (full stack), read its response headers
  `X-TRL-Tokens-Saved` / `X-TRL-Tokens-Before` / `X-TRL-Tokens-After` to show the
  per-request reduction (caching + compression + retrieval).
- Otherwise (plugin/retrieval tier only), report retrieval-slice stats: run a sample
  `python -m plugin.cli "<a real question about this repo>" --repo .` and compare the
  tokens returned (the header line prints slice + token counts) against the cost of
  reading the whole files those slices came from.

Remember the honest framing: the in-agent plugin delivers the RETRIEVAL tier, not the
full proxy-path headline.
