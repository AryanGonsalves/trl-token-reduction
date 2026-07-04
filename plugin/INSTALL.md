# Install the retrieval plugin into Claude Code

1. Deps (one time):  `pip install -r requirements.txt`  (installs `mcp`, `tree_sitter` and the 12-language grammar set: python, javascript, typescript, go, rust, java, c-sharp, c, cpp, ruby, php, kotlin). Missing grammars are skipped gracefully, so a partial install still works.
2. Copy `plugin/claude-code/.mcp.json` into the repo you want to work in (edit the
   two Windows paths if the project lives elsewhere; set `TRL_REPO` to that repo, or "." ).
3. Add the `plugin/claude-code/SKILL.md` guidance to that repo's `CLAUDE.md` (or install
   it as a skill) so Claude Code prefers `retrieve_code` over grepping.
4. Start Claude Code in the repo. It will connect to the `trl-retrieve` MCP server and,
   when it needs code context, call `retrieve_code("your question")` — getting slices
   instead of whole-file dumps.

CLI (no Claude Code needed):  `python -m plugin.cli "how does auth work?" --repo /path/to/repo`

---

## Install into Codex (OpenAI's coding agent)

Codex reads MCP servers from `~/.codex/config.toml` (global) or `.codex/config.toml`
(per-project, trusted only) — the same STDIO server works, unchanged.

1. Deps (one time): `pip install -r requirements.txt`
2. Copy the `[mcp_servers.trl-retrieve]` block from `plugin/codex/config.toml` into your
   `~/.codex/config.toml` (fix the two Windows paths if the project lives elsewhere; set
   `TRL_REPO` to the repo, or `"."`).
3. Start Codex in the repo. It launches the server on session start and exposes
   `retrieve_code` / `explain_symbol` next to its built-in tools.

**Why it's worth it on a Codex subscription:** since April 2026 Codex bills subscription
usage by API tokens (not per message), so trimming context with retrieval directly
stretches your 5-hour agentic window. (API-key mode: also set `openai_base_url` to the
proxy — commented in the sample — to apply all four levers.)
