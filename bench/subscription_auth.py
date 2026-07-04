"""Load the Claude Pro/Max SUBSCRIPTION OAuth token the same way VoiceClaw does.

Token is minted by Anthropic's official `claude setup-token` (format sk-ant-oat...)
and used as a Bearer token via anthropic.Anthropic(auth_token=...). We NEVER touch
browser cookies or web sessions -- only the officially-issued OAuth token.

Lookup order (mirrors voiceclaw.auth): env vars -> OS keychain (voiceclaw) -> file.
Personal-use only; do not ship a product that signs other users in this way.
"""
import json
import os
from pathlib import Path


def _real(v):
    # ignore empty / placeholder values so a stray env var can't cause a 401
    return v if (v and v.startswith("sk-ant-oat")) else None


def get_oauth_token():
    for var in ("CLAUDE_CODE_OAUTH_TOKEN", "ANTHROPIC_AUTH_TOKEN"):
        if _real(os.environ.get(var)):
            return os.environ[var]
    # OS keychain (Windows Credential Manager etc.), as voiceclaw stores it
    try:
        import keyring
        val = keyring.get_password("voiceclaw", "oauth_token")
        if val:
            return val
    except Exception:
        pass
    # file fallback ~/.voiceclaw/credentials.json
    try:
        f = Path(os.path.expanduser("~/.voiceclaw/credentials.json"))
        if f.exists():
            return json.loads(f.read_text(encoding="utf-8")).get("oauth_token")
    except Exception:
        pass
    return None
