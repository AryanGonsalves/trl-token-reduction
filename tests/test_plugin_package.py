"""Offline validation of the Claude Code plugin package: manifests parse with the
required fields, the MCP tools register on the real server, and the skill/commands
load. Retrieval-tier framing (no full-87% claim in agent-facing files)."""
import json, os, re, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _p(*a):
    return os.path.join(ROOT, *a)


def test_plugin_json_valid():
    pj = json.load(open(_p(".claude-plugin", "plugin.json")))
    assert pj["name"] == "trl"
    assert pj["version"] and pj["description"]
    assert pj["author"]["name"] == "AryanGonsalves"


def test_marketplace_json_valid():
    mk = json.load(open(_p(".claude-plugin", "marketplace.json")))
    assert mk["owner"]["name"] == "AryanGonsalves"
    p0 = mk["plugins"][0]
    assert p0["name"] == "trl" and p0["source"] == "./"


def test_mcp_json_declares_server():
    raw = open(_p(".mcp.json")).read()
    srv = json.loads(raw)["mcpServers"]["trl-retrieve"]
    assert srv["command"] == "python"
    assert srv["args"] == ["-m", "plugin.mcp_server"]
    assert "TRL_REPO" not in raw                       # resolved at runtime, not hardcoded
    assert srv["cwd"] == "${CLAUDE_PLUGIN_ROOT}"


def test_skill_loads_and_frontmatter():
    sk = open(_p("skills", "token-efficient-retrieval", "SKILL.md"), encoding="utf-8").read()
    m = re.match(r"^---\n(.*?)\n---\n", sk, re.S)
    assert m, "skill has no frontmatter"
    fm = m.group(1)
    assert re.search(r"^name:\s*token-efficient-retrieval", fm, re.M)
    assert re.search(r"^description:\s*\S", fm, re.M)
    assert "retrieve_code" in sk and "explain_symbol" in sk
    assert '"hosted"' in sk or 'rerank="hosted"' in sk
    assert "87%" not in sk               # retrieval-tier framing, no full-stack claim


def test_commands_present():
    for c in ("trl-index.md", "trl-status.md"):
        t = open(_p("commands", c), encoding="utf-8").read()
        assert t.startswith("---") and "description:" in t


def test_mcp_tools_register():
    pytest.importorskip("mcp")           # skip where the MCP SDK isn't installed
    os.environ["TRL_REPO"] = "."
    import importlib, asyncio
    srvmod = importlib.import_module("plugin.mcp_server")
    assert srvmod.FastMCP is not None
    names = sorted(t.name for t in asyncio.run(srvmod.mcp.list_tools()))
    assert names == ["explain_symbol", "retrieve_code"], names
