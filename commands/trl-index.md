---
description: Build or refresh the TRL code-retrieval index for the current project.
---

Build (or refresh) the token-efficient retrieval index so `retrieve_code` and
`explain_symbol` return exact slices for THIS project.

Run this from your project root:

```
python -m plugin.cli "index warmup" --repo .
```

It resolves the target project at runtime ($TRL_REPO -> $CLAUDE_PROJECT_DIR ->
nearest .git above cwd -> cwd) and writes the index to `<project>/.trl/index.json`,
so retrieval agrees no matter which directory the MCP server runs from. It walks
tree-sitter-supported source (Python, JS/TS, Go, Rust, Java, C#, C/C++, Ruby, PHP,
Kotlin) and is incremental by content hash, so re-running only re-parses what changed.

If `retrieve_code` replies that it "couldn't resolve your project", set `TRL_REPO` to
your project path (or pass `repo='/path'` to the tool) and run this again.
