# TRL — one-shot publish helper. It does git init/add/commit for you (with a
# safety check that blocks secrets), then pushes if a remote is set.
# Run it: right-click -> "Run with PowerShell", or:
#   powershell -ExecutionPolicy Bypass -File publish.ps1
$ErrorActionPreference = "Stop"
Set-Location -Path $PSScriptRoot

# identity (only sets if missing)
if (-not (git config user.email)) {
  git config user.name  "Aryan Gonsalves"
  git config user.email "aryan.gonsalves123@gmail.com"
}

if (-not (Test-Path .git)) { git init -b main | Out-Null }
git add -A

# SAFETY: refuse to continue if sensitive files or keys are staged
$bad = git ls-files | Select-String -Pattern '\.bat$|_result\.txt$|\.env$'
if ($bad) { Write-Host "ABORT — sensitive files staged:`n$bad" -ForegroundColor Red; exit 1 }
$keys = (git diff --cached) | Select-String -Pattern 'sk-proj-|sk-ant-api[0-9]|sk-ant-oat-'
if ($keys) { Write-Host "ABORT — possible API key in staged content. Not committing." -ForegroundColor Red; exit 1 }

git commit -m "Token Reduction Layer v0.1.0 - proxy, MCP plugin (Claude Code + Codex), composer extension"

if (-not (git remote)) {
  Write-Host ""
  Write-Host "Committed locally. Last step (needs your GitHub login):" -ForegroundColor Green
  Write-Host "  1) Create an EMPTY repo named 'trl-token-reduction' at https://github.com/new"
  Write-Host "     (no README/license - you already have them)"
  Write-Host "  2) Then run:"
  Write-Host "       git remote add origin https://github.com/AryanGonsalves/trl-token-reduction.git"
  Write-Host "       git push -u origin main"
} else {
  git push -u origin main
  Write-Host "Pushed." -ForegroundColor Green
}
