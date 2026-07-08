"""Offline tests for runtime project resolution (plugin.index_store._resolve_repo):
env precedence, git-root walk-up, cwd fallback, explicit-arg override."""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from plugin.index_store import _resolve_repo, _git_root, _has_explicit_repo


def test_explicit_arg_wins(monkeypatch):
    monkeypatch.setenv("TRL_REPO", "/env/repo")
    assert _resolve_repo("/given/proj") == os.path.abspath("/given/proj")


def test_env_precedence(monkeypatch, tmp_path):
    monkeypatch.setenv("TRL_REPO", str(tmp_path / "a"))
    monkeypatch.setenv("CLAUDE_PROJECT_DIR", str(tmp_path / "b"))
    assert _resolve_repo() == os.path.abspath(str(tmp_path / "a"))     # TRL_REPO first
    monkeypatch.delenv("TRL_REPO")
    assert _resolve_repo() == os.path.abspath(str(tmp_path / "b"))     # then CLAUDE_PROJECT_DIR


def test_git_root_walkup(monkeypatch, tmp_path):
    monkeypatch.delenv("TRL_REPO", raising=False)
    monkeypatch.delenv("CLAUDE_PROJECT_DIR", raising=False)
    (tmp_path / ".git").mkdir()
    deep = tmp_path / "pkg" / "sub"
    deep.mkdir(parents=True)
    monkeypatch.chdir(deep)
    assert os.path.realpath(_resolve_repo()) == os.path.realpath(str(tmp_path))


def test_git_root_none_at_filesystem_root():
    assert _git_root(os.sep) is None            # no /.git on the system


def test_cwd_fallback_when_no_signal(monkeypatch):
    monkeypatch.delenv("TRL_REPO", raising=False)
    monkeypatch.delenv("CLAUDE_PROJECT_DIR", raising=False)
    monkeypatch.setattr(os, "getcwd", lambda: os.sep)   # dir with no .git ancestor
    assert _resolve_repo() == os.sep


def test_has_explicit_repo(monkeypatch):
    monkeypatch.delenv("TRL_REPO", raising=False)
    monkeypatch.delenv("CLAUDE_PROJECT_DIR", raising=False)
    assert _has_explicit_repo() is False
    assert _has_explicit_repo("/x") is True
    monkeypatch.setenv("CLAUDE_PROJECT_DIR", "/y")
    assert _has_explicit_repo() is True


def test_mcp_target_guidance_when_unresolvable(monkeypatch):
    # MCP server cwd == plugin root + no env => can't confidently resolve => None
    # (so the tool returns the "run /trl-index or set TRL_REPO" hint).
    import importlib
    srv = importlib.import_module("plugin.mcp_server")
    monkeypatch.delenv("TRL_REPO", raising=False)
    monkeypatch.delenv("CLAUDE_PROJECT_DIR", raising=False)
    monkeypatch.chdir(srv._PLUGIN_ROOT)
    assert srv._target(None) is None
    assert srv._target("/some/proj") == os.path.abspath("/some/proj")   # explicit works
