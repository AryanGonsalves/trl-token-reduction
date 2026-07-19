"""Probe whether the DEPLOYED trl plugin logs a real retrieve_code call.
Usage: verify_logging.py <launcher.mjs> <proj_dir> <mode>   mode in {normal,setx}"""
import asyncio, os, sys
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

LAUNCHER, PROJ, MODE = sys.argv[1], sys.argv[2], sys.argv[3]

async def main():
    env = dict(os.environ)
    for k in ("CLAUDE_PROJECT_DIR", "TRL_SAVINGS_LOG", "TRL_REPO"):
        env.pop(k, None)
    cwd = PROJ
    if MODE == "normal":                       # a healthy session: project dir set
        env["CLAUDE_PROJECT_DIR"] = PROJ
    elif MODE == "setx":                        # the fix: explicit log path + hostile cwd
        env["TRL_REPO"] = PROJ
        env["TRL_SAVINGS_LOG"] = os.path.join(PROJ, ".trl", "savings.jsonl")
        cwd = r"C:\Windows"
    p = StdioServerParameters(command="node", args=[LAUNCHER], env=env, cwd=cwd)
    async with stdio_client(p) as (r, w):
        async with ClientSession(r, w) as s:
            await s.initialize()
            res = await s.call_tool("retrieve_code", {"query": "config settings tunables"})
            print("  retrieve_code ->", len(res.content[0].text) if res.content else 0, "chars")

asyncio.run(main())
