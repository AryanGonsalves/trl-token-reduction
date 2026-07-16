import json
out = []
home = r"C:\Users\Aryan's Laptop"
try:
    s = json.load(open(home + r"\.claude\settings.json", encoding="utf-8"))
    out.append("settings.json keys: " + str(list(s.keys())))
    for k in ("enabledPlugins", "plugins", "enableAllProjectMcpServers"):
        if k in s:
            out.append("settings." + k + " = " + json.dumps(s[k]))
except Exception as e:
    out.append("settings.json err: %r" % (e,))
try:
    c = json.load(open(home + r"\.claude.json", encoding="utf-8"))
    keys = [k for k in c.keys() if "lugin" in k.lower() or "mcp" in k.lower()]
    out.append(".claude.json plugin/mcp-ish top keys: " + str(keys))
    for k in keys:
        out.append(".claude.json %s = %s" % (k, json.dumps(c[k])[:2000]))
    projs = c.get("projects", {})
    out.append("project count: %d" % len(projs))
    for p, v in projs.items():
        interesting = {kk: vv for kk, vv in v.items() if "lugin" in kk.lower() or "mcp" in kk.lower()}
        if "roblox" in p.lower() or "token reduction" in p.lower() or interesting:
            out.append("project %s: %s" % (p, json.dumps(interesting)[:1200]))
except Exception as e:
    out.append(".claude.json err: %r" % (e,))
print("\n".join(out))
