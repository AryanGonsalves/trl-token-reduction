"""Reproduce Claude Code's LIVE spawn of the exe MCP server against the INSTALLED
plugin, to find why form C gets -32000 even though the exe is healthy.

Leading hypothesis: `cmd /c trl-retrieve.exe` relies on cmd searching its current
directory for the bare exe name. If the spawn environment has
NoDefaultCurrentDirectoryInExePath set (common under VS Code / Node), that search is
disabled and cmd can't find the exe -> server never starts -> -32000. An EXPLICIT
relative path `.\trl-retrieve.exe` is immune to that setting.

Usage:  py -3.12 packaging\diag_live_launch.py "<PLUGIN_ROOT>"
        (PLUGIN_ROOT = the installed plugin dir that contains bin\trl-retrieve.exe)
"""
import asyncio
import os
import sys

PLUGIN_ROOT = (sys.argv[1] if len(sys.argv) > 1 else os.environ.get("PLUGIN_ROOT", "")).rstrip("\\/")


async def _try(label, command, args, cwd, extra_env=None, timeout=25.0):
    from mcp import ClientSession, StdioServerParameters
    from mcp.client.stdio import stdio_client
    env = dict(os.environ)
    if extra_env:
        env.update(extra_env)

    async def _run():
        params = StdioServerParameters(command=command, args=args, env=env, cwd=cwd)
        async with stdio_client(params) as (r, w):
            async with ClientSession(r, w) as s:
                await s.initialize()
                tools = await s.list_tools()
                return True, "tools=" + str([t.name for t in tools.tools])

    try:
        ok, detail = await asyncio.wait_for(_run(), timeout=timeout)
    except Exception as e:
        ok, detail = False, (f"{type(e).__name__}: {e}".replace("\n", " "))[:280]
    print(f"[{'PASS' if ok else 'FAIL'}] {label}")
    print(f"        {detail}")
    return ok


async def main():
    bindir = os.path.join(PLUGIN_ROOT, "bin")
    exe = os.path.join(bindir, "trl-retrieve.exe")
    print(f"PLUGIN_ROOT = {PLUGIN_ROOT}")
    print(f"bin exists  = {os.path.isdir(bindir)} ; exe exists = {os.path.isfile(exe)}")
    hardened = {"NoDefaultCurrentDirectoryInExePath": "1"}
    print("=" * 72)
    # C: bare exe name via cmd, relies on cmd searching cwd.
    await _try("C  cmd /c trl-retrieve.exe                (cwd=bin)",
               "cmd", ["/c", "trl-retrieve.exe"], bindir)
    # C under a hardened env -> should FAIL if the hypothesis holds.
    await _try("C  cmd /c trl-retrieve.exe   [HARDENED]   (cwd=bin)",
               "cmd", ["/c", "trl-retrieve.exe"], bindir, hardened)
    # D: EXPLICIT relative path -> immune to NoDefaultCurrentDirectoryInExePath.
    await _try("D  cmd /c .\\trl-retrieve.exe             (cwd=bin)",
               "cmd", ["/c", ".\\trl-retrieve.exe"], bindir)
    await _try("D  cmd /c .\\trl-retrieve.exe [HARDENED]  (cwd=bin)",
               "cmd", ["/c", ".\\trl-retrieve.exe"], bindir, hardened)
    # Control: absolute exe path directly (no cmd) -> proves exe+handshake healthy.
    await _try("control) absolute exe path directly",
               exe, [], PLUGIN_ROOT)
    print("=" * 72)


if __name__ == "__main__":
    asyncio.run(main())
