#!/usr/bin/env node
/*
 * Cross-platform launcher for the TRL retrieval MCP server (trl-retrieve).
 *
 * Why a Node launcher: Claude Code's plugin .mcp.json has no per-OS field, does NOT
 * apply a `cwd`, and only interpolates ${CLAUDE_PLUGIN_ROOT} in command/args. Node is
 * the one interpreter guaranteed present (Claude Code runs on it), so we launch via
 *   command: "node", args: ["${CLAUDE_PLUGIN_ROOT}/bin/launch.mjs"]
 * and do the OS/arch dispatch here. This resolves its OWN directory (import.meta.url),
 * so it's immune to cwd/interpolation/PATH quirks, and spawns the native binary directly
 * (no cmd wrapper) so spaces/apostrophes in the path are irrelevant.
 */
import { spawn } from "node:child_process";
import { fileURLToPath } from "node:url";
import { dirname, join } from "node:path";
import { existsSync } from "node:fs";

const binDir = dirname(fileURLToPath(import.meta.url)); // .../<plugin>/bin
const pluginRoot = dirname(binDir);                     // .../<plugin>

// Candidate frozen-binary names, most-specific first. The generic Windows name
// (trl-retrieve.exe) is kept last so an existing single-OS build still works.
function candidates() {
  const p = process.platform, a = process.arch;
  if (p === "win32") return ["trl-retrieve-win-x64.exe", "trl-retrieve.exe"];
  if (p === "darwin") return a === "arm64"
    ? ["trl-retrieve-macos-arm64", "trl-retrieve-macos"]
    : ["trl-retrieve-macos-x64", "trl-retrieve-macos"];
  if (p === "linux") return ["trl-retrieve-linux-x64", "trl-retrieve-linux"];
  return [];
}

let cmd, args, extraEnv = {};
const found = candidates().map((n) => join(binDir, n)).find((p) => existsSync(p));
if (found) {
  cmd = found;
  args = [];
} else {
  // No prebuilt binary for this platform -> run from source via Python (needs deps).
  cmd = process.platform === "win32" ? "python" : "python3";
  args = ["-m", "plugin.mcp_server"];
  extraEnv.PYTHONPATH = pluginRoot;
}

const child = spawn(cmd, args, {
  cwd: pluginRoot,                       // launcher sets cwd (Claude Code doesn't)
  stdio: "inherit",                      // transparent MCP stdio passthrough
  env: { ...process.env, ...extraEnv },
});
child.on("error", (e) => {
  console.error(`[trl launcher] failed to start ${cmd}: ${e.message}`);
  process.exit(1);
});
child.on("exit", (code, signal) => process.exit(code ?? (signal ? 1 : 0)));
