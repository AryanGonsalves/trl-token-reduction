import os, json, importlib
import pytest

def _rc():
    srv = importlib.import_module("plugin.mcp_server")
    fn = getattr(srv, "retrieve_code", None)
    if fn is None:
        pytest.skip("mcp SDK not installed")
    return fn.fn if hasattr(fn, "fn") else fn

_REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

def test_savings_log_written(tmp_path, monkeypatch):
    log = tmp_path / "savings.jsonl"
    monkeypatch.setenv("TRL_SAVINGS_LOG", str(log))
    _rc()("how does compression preserve numbers", repo=_REPO)
    assert log.exists()
    rec = json.loads(log.read_text().splitlines()[0])
    assert rec["tool"] == "retrieve_code"
    assert rec["wholefile_tokens"] >= rec["slice_tokens"]
    assert rec["saved"] == max(0, rec["wholefile_tokens"] - rec["slice_tokens"])

def test_no_log_without_env(tmp_path, monkeypatch):
    monkeypatch.delenv("TRL_SAVINGS_LOG", raising=False)
    out = _rc()("anything", repo=_REPO)   # must not crash or write
    assert isinstance(out, str)
