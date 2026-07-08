---
name: token-efficient-retrieval
description: Use the trl-retrieve MCP tools to fetch exact code slices instead of reading whole files, saving context tokens. Trigger whenever exploring or answering questions about the current codebase.
---

# Token-efficient code retrieval

When you need to understand or answer a question about this codebase, DO NOT grep and
read whole files. Instead:

- Call **`retrieve_code(query)`** (MCP server `trl-retrieve`) with a natural-language
  question. It returns the exact relevant source slices (functions / classes / methods)
  at a fraction of the tokens of opening files.
- Call **`explain_symbol(name)`** to fetch the full source of a named symbol.
- Only fall back to reading whole files if retrieval returns nothing relevant.

The index builds automatically on your first `retrieve_code` call (cached at `<project>/.trl/index.json`, incremental). Just call the tools directly — no setup step. If a tool says it "couldn't resolve your project", set `TRL_REPO` or pass `repo='/path'`.

## Optional precision (off by default)

Retrieval ranks by keyword + call-graph. For vague natural-language questions where the
right symbol isn't surfacing, an OPTIONAL hosted rerank exists (`retrieve(rerank="hosted")`)
that uses YOUR OWN `ANTHROPIC_API_KEY` (~1 cent/query via claude-haiku-4-5). It is a
PRECISION option, not a token saver, and is OFF by default.

## Honest scope (retrieval tier)

This skill delivers the RETRIEVAL lever only: it cuts context tokens by fetching slices
instead of whole files. It does NOT deliver the full proxy-path headline savings —
prefix caching and tail compression require running the local proxy and pointing your
agent's base URL at it (see `/trl-status` and the README two-tier note).
