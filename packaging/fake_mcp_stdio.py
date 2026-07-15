"""Minimal fake MCP STDIO server used ONLY by test_mcp_launch.py --self-check.
Lets us prove the launch harness (interpolation + spawn + handshake + pass/fail
reporting) on any OS, without the Windows-only trl-retrieve.exe."""
import asyncio
from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp import types

app = Server("fake-trl")


@app.list_tools()
async def _list():
    schema = {"type": "object", "properties": {"query": {"type": "string"}}}
    return [
        types.Tool(name="retrieve_code", description="fake", inputSchema=schema),
        types.Tool(name="explain_symbol", description="fake", inputSchema=schema),
    ]


@app.call_tool()
async def _call(name, arguments):
    return [types.TextContent(type="text", text=f"FAKE {name} ok args={arguments}")]


async def _main():
    async with stdio_server() as (r, w):
        await app.run(r, w, app.create_initialization_options())


if __name__ == "__main__":
    asyncio.run(_main())
