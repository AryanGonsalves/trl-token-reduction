# TRL — one-shot publish helper. Does git init/add/commit for you (with a safety
# check that blocks secrets), then pushes if a remote is set. Safe to re-run.
# Run it: right-click -> "Run with PowerShell"  (the window now stays open so you
# can read the result), or from a terminal:  powershell -ExecutionPolicy Bypass -File publish.ps1
Set-Location -Path $PSScriptRoot
try {
    # 0) git present?
    git --version *> $null
    if ($LASTEXITCODE -ne 0) { throw "git is not installed or not on PATH. Install Git for Windows: https://git-scm.com/download/win" }

    # 1) identity (only if missing)
    if (-not (git config user.email)) {
        git config user.name  "Aryan Gonsalves"
        git config user.email "aryan.gonsalves123@gmail.com"
    }

    # 2) init if needed
    if (-not (Test-Path .git)) { git init -b main | Out-Null; Write-Host "Initialized new git repo." }
    git add -A

    # 3) SAFETY: block secrets
    $bad = git ls-files | Select-String -Pattern '\.bat$|_result\.txt$|\.env$'
    if ($bad) { throw "Sensitive files are staged:`n$bad" }
    $keys = (git diff --cached) | Select-String -Pattern 'sk-proj-[A-Za-z0-9_-]{20,}|sk-ant-api[0-9]{2}-[A-Za-z0-9_-]{20,}|sk-ant-oat-[A-Za-z0-9_-]{20,}'
    if ($keys) { throw "Possible API key found in staged content. Not committing." }

    # 4) commit only if there is something to commit
    git diff --cached --quiet
    if ($LASTEXITCODE -ne 0) {
        git commit -m "Token Reduction Layer v0.1.0 - proxy, MCP plugin (Claude Code + Codex), composer extension" | Out-Null
        Write-Host "Committed." -ForegroundColor Green
    } else {
        Write-Host "Nothing new to commit (already committed)." -ForegroundColor Yellow
    }

    Write-Host "`nLatest commit:" -ForegroundColor Cyan
    git log --oneline -1

    # 5) push or instruct
    if (git remote) {
        Write-Host "`nPushing to remote..." -ForegroundColor Cyan
        git push -u origin main
        Write-Host "Pushed. Your repo is live." -ForegroundColor Green
    } else {
        Write-Host "`nCommitted locally. LAST STEP (needs your GitHub login):" -ForegroundColor Green
        Write-Host "  1) Create an EMPTY repo named 'trl-token-reduction' at https://github.com/new"
        Write-Host "     (do NOT add a README or license - you already have them)"
        Write-Host "  2) Copy-paste these two lines here:" -ForegroundColor Green
        Write-Host "       git remote add origin https://github.com/AryanGonsalves/trl-token-reduction.git" -ForegroundColor White
        Write-Host "       git push -u origin main" -ForegroundColor White
    }
}
catch {
    Write-Host "`nERROR: $_" -ForegroundColor Red
}
finally {
    Write-Host ""
    Read-Host "Press Enter to close"
}
