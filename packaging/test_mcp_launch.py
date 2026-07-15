"""Iterative MCP launch harness -- find an .mcp.json launch form that Claude Code
can actually spawn for the frozen trl-retrieve.exe.

Background (CONTEXT.md #50): the exe-backed config failed live with -32000 because
Claude Code interpolates ${CLAUDE_PLUGIN_ROOT} in the `cwd` and `env` fields but NOT
in the `command` field. This harness reproduces that spawn faithfully so we can test
several candidate launch forms in seconds -- instead of the slow publish -> /plugin
update -> /mcp reconnect loop.

Faithful model:
  * `cwd`  values: ${CLAUDE_PLUGIN_ROOT} IS substituted (Claude Code does this).
  * `env`  values: ${CLAUDE_PLUGIN_ROOT} IS substituted (Claude Code does this).
  * `command` / `args`: left LITERAL (Claude Code does NOT substitute) -- so a naive
    "${CLAUDE_PLUGIN_ROOT}/bin/trl-retrieve.exe" command reproduces the -32000 failure.

Usage:
  py -3.12 packaging/test_mcp_launch.py              # test real exe candidates (Windows)
  py -3.12 packaging/test_mcp_launch.py --self-check # offline engine proof (any OS, fake server)
"""
import asyncio
import os
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
# In real Claude Code, CLAUDE_PLUGIN_ROOT == the plugin install dir (which has bin/).
# For local testing the repo root plays that role (it also has bin/trl-retrieve.exe).
PLUGIN_ROOT = os.environ.get("TRL_TEST_PLUGIN_ROOT", ROOT)


def _interp(value):
    """Substitute ${CLAUDE_PLUGIN_ROOT} the way Claude Code does (cwd/env only)."""
    if value is None:
        return None
    return value.replace("${CLAUDE_PLUGIN_ROOT}", PLUGIN_ROOT)


def _build_params(cand):
    """Turn a candidate dict into StdioServerParameters, applying Claude Code's rules."""
    from mcp import StdioServerParameters
    env = dict(os.environ)
    for k, v in (cand.get("env") or {}).items():
        env[k] = _interp(v)                      # env values ARE interpolated
    cwd = _interp(cand.get("cwd"))               # cwd IS interpolated
    kwargs = dict(
        command=cand["command"],                 # command is LEFT LITERAL (faithful)
        args=list(cand.get("args", [])),         # args are LEFT LITERAL (faithful)
        env=env,
    )
    if cwd:
        kwargs["cwd"] = cwd
    return StdioServerParameters(**kwargs)


async def _try_candidate(cand, timeout=25.0):
    """Spawn one candidate, run initialize + list_tools + call_tool. Return (ok, detail)."""
    from mcp import ClientSession
    from mcp.client.stdio import stdio_client
    params = _build_params(cand)

    async def _run():
        async with stdio_client(params) as (r, w):
            async with ClientSession(r, w) as s:
                await s.initialize()
                tools = await s.list_tools()
                names = [t.name for t in tools.tools]
                call = cand.get("call", ("retrieve_code", {"query": "compression"}))
                chars = -1
                try:
                    res = await s.call_tool(*call)
                    chars = len(res.content[0].text) if res.content else 0
                except Exception as e:  # tools listed but call failed -- still informative
                    return True, f"tools={names}; call FAILED: {type(e).__name__}: {e}"
                return True, f"tools={names}; {call[0]} -> {chars} chars"

    try:
        return await asyncio.wait_for(_run(), timeout=timeout)
    except Exception as e:
        msg = f"{type(e).__name__}: {e}".strip().replace("\n", " ")
        return False, msg[:300]


def _windows_candidates():
    """Candidate .mcp.json launch forms for the real Windows exe (bin/trl-retrieve.exe)."""
    return [
        # Repro of the #50 failure: exe path in `command` with an un-interpolated template.
        {"label": "naive (repro -32000): ${...} in command",
         "command": "${CLAUDE_PLUGIN_ROOT}/bin/trl-retrieve.exe", "args": [],
         "cwd": "${CLAUDE_PLUGIN_ROOT}"},
        # A) cmd /c + env-expanded ABSOLUTE path, UNQUOTED. Expected FAIL when the
        #    plugin root contains spaces: cmd expands then splits at the first space
        #    ("'D:\\Token' is not recognized...").
        {"label": "A) cmd /c %CLAUDE_PLUGIN_ROOT%\\bin\\trl-retrieve.exe (unquoted)",
         "command": "cmd", "args": ["/c", "%CLAUDE_PLUGIN_ROOT%\\bin\\trl-retrieve.exe"],
         "cwd": "${CLAUDE_PLUGIN_ROOT}",
         "env": {"CLAUDE_PLUGIN_ROOT": "${CLAUDE_PLUGIN_ROOT}"}},
        # A2) same but the arg carries its own double quotes so cmd sees a quoted path
        #    even after %...% expands to a path with spaces.
        {"label": 'A2) cmd /c "%CLAUDE_PLUGIN_ROOT%\\bin\\trl-retrieve.exe" (quoted)',
         "command": "cmd", "args": ["/c", '"%CLAUDE_PLUGIN_ROOT%\\bin\\trl-retrieve.exe"'],
         "cwd": "${CLAUDE_PLUGIN_ROOT}",
         "env": {"CLAUDE_PLUGIN_ROOT": "${CLAUDE_PLUGIN_ROOT}"}},
        # B) relative command resolved via interpolated cwd. CAUTION: CreateProcess
        #    resolves a relative exe path against the PARENT's cwd. In this harness the
        #    parent cwd == plugin root, so B can PASS here yet fail in real Claude Code
        #    (whose cwd is the user's project dir). Do NOT ship B even if it passes.
        {"label": "B) command=bin\\trl-retrieve.exe, cwd=${...} (harness-only, do not ship)",
         "command": "bin\\trl-retrieve.exe", "args": [], "cwd": "${CLAUDE_PLUGIN_ROOT}"},
        # C) cmd /c bare exe name, cwd = the bin dir (cmd searches its own cwd first).
        #    No quoting needed; independent of the parent's cwd. Most robust portable form.
        {"label": "C) cmd /c trl-retrieve.exe, cwd=${...}\\bin",
         "command": "cmd", "args": ["/c", "trl-retrieve.exe"],
         "cwd": "${CLAUDE_PLUGIN_ROOT}\\bin"},
        # Control: absolute path resolved by THIS harness (proves exe+harness are healthy).
        {"label": "control) absolute exe path (works, not portable)",
         "command": os.path.join(PLUGIN_ROOT, "bin", "trl-retrieve.exe"), "args": [],
         "cwd": PLUGIN_ROOT},
    ]


def _self_check_candidates(tmp):
    """OS-neutral candidates using the fake server -- proves the harness engine offline."""
    fake = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fake_mcp_stdio.py")
    return [
        # Good: python + fake server, cwd interpolated -> must PASS.
        {"label": "self-check GOOD (fake server via python)",
         "command": sys.executable, "args": [fake], "cwd": "${CLAUDE_PLUGIN_ROOT}",
         "expect": True},
        # Broken: an un-interpolated ${...} left in `command` (faithful) -> must FAIL,
        # mirroring how the real naive exe config dies with -32000.
        {"label": "self-check BROKEN (${...} in command, not interpolated)",
         "command": "${CLAUDE_PLUGIN_ROOT}/no_such/fake.py", "args": [],
         "cwd": "${CLAUDE_PLUGIN_ROOT}", "expect": False},
    ]


async def _run_all(candidates):
    print(f"CLAUDE_PLUGIN_ROOT (test value) = {PLUGIN_ROOT}")
    print(f"exe present: {os.path.exists(os.path.join(PLUGIN_ROOT, 'bin', 'trl-retrieve.exe'))}")
    print("=" * 72)
    results = []
    for cand in candidates:
        ok, detail = await _try_candidate(cand)
        status = "PASS" if ok else "FAIL"
        print(f"[{status}] {cand['label']}")
        print(f"        {detail}")
        results.append((cand, ok, detail))
    print("=" * 72)
    working = [c["label"] for c, ok, _ in results if ok and not c["label"].startswith("naive")
               and not c["label"].startswith("control") and not c["label"].startswith("self-check")]
    if working:
        print("RECOMMENDED launch form(s) that connected:")
        for w in working:
            print("  ->", w)
    else:
        print("No portable candidate connected. Inspect FAIL details above.")
    return results


def _self_check():
    with tempfile.TemporaryDirectory() as tmp:
        cands = _self_check_candidates(tmp)
        results = asyncio.run(_run_all(cands))
    ok = True
    for cand, got, detail in results:
        want = cand.get("expect")
        if want is not None and got != want:
            print(f"SELF-CHECK ASSERT FAILED: {cand['label']} expected "
                  f"{'PASS' if want else 'FAIL'} but got {'PASS' if got else 'FAIL'}")
            ok = False
    print("SELF-CHECK:", "OK (engine faithful: good spawns, un-interpolated command fails)"
          if ok else "BROKEN")
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    if "--self-check" in sys.argv:
        _self_check()
    else:
        asyncio.run(_run_all(_windows_candidates()))
