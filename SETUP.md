# TRL — plugin setup & savings measurement

Install the TRL retrieval plugin for your coding agent (Claude Code) and measure the
input tokens it saves as you work.

## What this gives you
The plugin exposes `retrieve_code` / `explain_symbol`, so the agent pulls only the
relevant code slices instead of reading whole files — the **retrieval lever**, the
biggest conflict-free win inside an already-cached agent. (Prefix caching + history
compression are the *proxy* surface — see the README; don't stack the proxy in front
of Claude Code, which does its own caching.)

## Prerequisites (one-time)
- Python 3.10+ on your PATH.
- The server's dependencies:
  ```
  pip install -r requirements-plugin.txt   # all languages + runtime; no benchmark/API bloat
  ```

## 1. Install the plugin in Claude Code
```
/plugin marketplace add AryanGonsalves/trl-token-reduction
/plugin install trl
```
The plugin auto-targets your current project via `CLAUDE_PROJECT_DIR`. If a tool ever
replies *"couldn't resolve your project"*, either set `TRL_REPO=/path/to/project`
before launching, or call the tool with `repo="/path/to/project"`.

## 2. Turn on savings tracking (optional)
Set this before launching Claude Code, so every retrieval is logged:
```
# Windows PowerShell
$env:TRL_SAVINGS_LOG = "$PWD\.trl\savings.jsonl"
# macOS / Linux
export TRL_SAVINGS_LOG="$PWD/.trl/savings.jsonl"
```
Then use Claude Code normally. Each `retrieve_code` / `explain_symbol` call records the
slice tokens it returned vs the whole file(s) it replaced.

## 3. Read your savings
```
python -m validate.savings_report "<path to savings.jsonl>"
```
Reports **adoption** (how often the tools were actually called) and **tokens saved vs
whole-file reads**, cumulative across every session.

> Savings only accrue when the agent actually calls the retrieval tools. If adoption is
> low, prompt it to *"use retrieve_code for code context"* — the bundled
> `token-efficient-retrieval` skill nudges it, but you can reinforce it.

## Example: a Rojo / Roblox (Luau) project
TRL indexes Luau, so Roblox codebases work. Point Claude Code at your Rojo project
folder (the one holding your `.luau` sources) and build — the agent retrieves slices
from your Luau instead of whole ModuleScripts. Visual/asset work, built-in proximity
voice, and publishing stay in Roblox Studio.

## Seamless install (Windows, v0.2.0+) — no Python needed
As of v0.2.0 the plugin ships a self-contained `bin/trl-retrieve.exe` and `.mcp.json` launches
it directly, so on Windows you do NOT need Python, pip, a venv, or `requirements-plugin.txt` —
just install the plugin:
```
/plugin marketplace add https://github.com/AryanGonsalves/trl-token-reduction
/plugin install trl
```
The prerequisites/venv steps above are only for the cross-platform **source** install (macOS/Linux,
or if you prefer running from Python). To use that path, copy `.mcp.python.json.txt` over `.mcp.json`.
