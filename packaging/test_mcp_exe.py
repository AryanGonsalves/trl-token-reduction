"""Prove the frozen trl-retrieve.exe serves the MCP protocol over STDIO (zero deps at
runtime -- this harness uses python+mcp only as a CLIENT to talk to the exe)."""
import asyncio, os
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
EXE = os.path.join(ROOT, "dist", "trl-retrieve.exe")

async def main():
    env = dict(os.environ); env["CLAUDE_PROJECT_DIR"] = ROOT
    params = StdioServerParameters(command=EXE, args=[], env=env)
    async with stdio_client(params) as (r, w):
        async with ClientSession(r, w) as s:
            await s.initialize()
            tools = await s.list_tools()
            print("EXE-MCP OK. tools:", [t.name for t in tools.tools])
            res = await s.call_tool("retrieve_code", {"query": "preserve facts compression"})
            txt = res.content[0].text if res.content else ""
            print("retrieve_code via exe -> returned", len(txt), "chars; head:",
                  (txt.splitlines()[0] if txt.strip() else "(empty)"))

asyncio.run(main())
