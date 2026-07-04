# trl-retrieve (code retrieval)

When you need to understand this codebase, DO NOT grep and read whole files.
Call the MCP tool **`retrieve_code`** (server `trl-retrieve`) with a natural-language
question — it returns the exact relevant source slices (function/class/method) at a
fraction of the tokens. Use **`explain_symbol`** to fetch the full source of a named
symbol. Only fall back to reading whole files if retrieval returns nothing relevant.
