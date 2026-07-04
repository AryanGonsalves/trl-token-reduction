# Publishing to GitHub

Everything is prepared and secret-scrubbed. Run these on your machine (where `D:\`
is native — git can't run through the sandbox mount). Open a terminal in the repo:

```powershell
cd "D:\Token Reduction Layer for LLM"

git init -b main
git add -A

# SAFETY CHECK — both of these must print nothing:
git ls-files | findstr /I ".bat _result.txt .env"
git diff --cached | findstr /R "sk-proj- sk-ant-api sk-ant-oat"

git commit -m "Token Reduction Layer v0.1.0 — caching, compression+guard, retrieval, cascade; proxy, MCP plugin (Claude Code + Codex), composer extension"
```

Then create an EMPTY repo on github.com (no README/license — you already have them),
named e.g. `trl-token-reduction`, and:

```powershell
git remote add origin https://github.com/AryanGonsalves/trl-token-reduction.git
git push -u origin main
```

## Before you push — two things
1. **Rotate the two API keys** that were in the .bat files (OpenAI `sk-proj-…`,
   Anthropic `sk-ant-api03-…`). They sat in plaintext, so treat them as exposed even
   though they're now scrubbed and git-ignored. Generate fresh keys in each dashboard.
2. The GitHub URLs in `pyproject.toml`, `CONTRIBUTING.md`, and the commands above
   are already set to `AryanGonsalves`. Name the GitHub repo `trl-token-reduction`
   to match (or edit those URLs if you choose a different repo name).

## Optional: publish to PyPI later
```powershell
pip install build twine
python -m build           # makes dist/*.whl and *.tar.gz
twine upload dist/*       # needs a PyPI account + token
```
