import json, shutil, os, time
home = r"C:\Users\Aryan's Laptop"
targets = [
    home + r"\.claude\plugins\marketplaces\trl-marketplace\.mcp.json",
    home + r"\.claude\plugins\cache\trl-marketplace\trl\0.2.3\.mcp.json",
]
cfg = {
    "mcpServers": {
        "trl-retrieve": {
            "command": "${CLAUDE_PLUGIN_ROOT}\\bin\\trl-retrieve.exe",
            "args": []
        }
    }
}
for t in targets:
    if os.path.exists(t) and not os.path.exists(t + ".bak"):
        shutil.copy2(t, t + ".bak")
        print("backed up:", t + ".bak")
    with open(t, "w", encoding="utf-8") as f:
        json.dump(cfg, f, indent=2)
    print("wrote candidate E (interpolated command) to:", t)
    print(open(t, encoding="utf-8").read())
