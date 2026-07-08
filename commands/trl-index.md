---
description: Build or refresh the TRL code-retrieval index for the current project.
---

The retrieval index behind `retrieve_code` and `explain_symbol` is built and kept current
**automatically** — there is no manual command to run.

- It builds on your **first `retrieve_code` / `explain_symbol` call** for a project and is
  cached at `<project>/.trl/index.json`.
- It is **incremental**: each call only re-parses the files that changed, so it stays fresh
  as you edit.
- It covers tree-sitter source: Python, JS/TS, Go, Rust, Java, C#, C/C++, Ruby, PHP, Kotlin,
  **Luau/Roblox**.

**To force a build/refresh right now**, just call `retrieve_code` with any query, e.g.
`retrieve_code("overview")`. That resolves the project
(`$TRL_REPO` → `$CLAUDE_PROJECT_DIR` → nearest `.git` above cwd → cwd), (re)builds the index,
and writes `<project>/.trl/index.json`.

Do **not** run `python -m plugin.cli` from your project folder — the `plugin` module lives in
the plugin's own directory, so that fails with "No module named plugin". Use `retrieve_code`.

If `retrieve_code` replies **"couldn't resolve your project"**, set `TRL_REPO` to your project
path (or pass `repo='/path'` to the tool) and call it again.
