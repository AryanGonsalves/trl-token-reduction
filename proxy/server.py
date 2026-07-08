"""Drop-in OpenAI-compatible proxy. Point your client's base_url here; every
/v1/chat/completions request gets the token-reduction levers applied, then is
forwarded upstream with YOUR Authorization header (the proxy never stores keys).

Run:  python -m proxy.server            # listens on :8899, forwards to OpenAI
Then: client base_url = http://localhost:8899/v1   (key unchanged)

Stdlib only (http.server + urllib) so it has zero extra deps. Adds response
header  X-TRL-Tokens-Saved  so you can see the reduction per request."""
from __future__ import annotations

import json
import os
import sys
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from trl import Engine
from trl.util import load_config
from proxy.transform import transform_chat_request, transform_anthropic_request
from proxy.compress_endpoint import handle_compress

_DEFAULT_CFG = {
    "arms": {"treatment": {"native_prompt_cache": True, "compress_history": True,
                            "compress_tool_outputs": True, "compression_mode": "safe"}},
    "local_model": {"provider": "none"},
    "retrieval": {"enabled": True, "token_budget": 800, "k": 8, "expand_call_graph": True},
}


def _load_cfg():
    # Prefer an explicit path, then ./config.yaml, then a repo-relative copy;
    # fall back to a sane built-in default so the pip-installed CLI runs anywhere.
    import os as _os
    for cand in (_os.environ.get("TRL_CONFIG"), "config.yaml",
                 _os.path.join(_os.path.dirname(__file__), "..", "config.yaml")):
        if cand and _os.path.exists(cand):
            try:
                return load_config(cand)
            except Exception:
                pass
    return _DEFAULT_CFG


_CFG = _load_cfg()
_ENGINE = Engine(_CFG)
_UPSTREAM = os.environ.get("TRL_UPSTREAM", "https://api.openai.com")


_MAX_BODY = 10 * 1024 * 1024        # 10 MB request-body cap (reject before read)
_ALLOWED_ORIGINS = {"https://claude.ai"}
_CORS_BASE = {
    "Access-Control-Allow-Methods": "POST, OPTIONS",
    "Access-Control-Allow-Headers": "Content-Type",
    "Access-Control-Allow-Private-Network": "true",
}


class Handler(BaseHTTPRequestHandler):
    def _cors(self):
        # Scope CORS: the browser extension's origin is chrome-extension://<id>
        # (random per install, so allow the scheme) plus claude.ai. Arbitrary
        # websites get NO Access-Control-Allow-Origin, so a browser refuses to let
        # them read responses from the local proxy. Non-browser SDK clients ignore
        # CORS entirely, so this doesn't affect the base_url-swap proxy usage.
        h = dict(_CORS_BASE)
        origin = self.headers.get("Origin", "")
        if origin.startswith("chrome-extension://") or origin in _ALLOWED_ORIGINS:
            h["Access-Control-Allow-Origin"] = origin
            h["Vary"] = "Origin"
        return h

    def do_OPTIONS(self):
        self._send(204, b"", self._cors())

    def do_GET(self):
        # Lightweight liveness probe so clients (e.g. the browser extension) can
        # tell "engine running" from "engine down" and show a useful message.
        if self.path.rstrip("/").endswith("/health"):
            return self._send(200, b'{"status":"ok","service":"trl-proxy"}',
                              {"Content-Type": "application/json", **self._cors()})
        return self._send(404, b'{"error":"not found"}',
                          {"Content-Type": "application/json", **self._cors()})

    def _send(self, code, body: bytes, headers=None):
        self.send_response(code)
        for k, v in (headers or {}).items():
            self.send_header(k, v)
        self.end_headers()
        self.wfile.write(body)

    def do_POST(self):
        try:
            n = int(self.headers.get("Content-Length") or 0)
        except (TypeError, ValueError):
            return self._send(411, b'{"error":"missing or invalid Content-Length"}',
                              {"Content-Type": "application/json", **self._cors()})
        if n > _MAX_BODY:                       # reject oversized bodies BEFORE read
            return self._send(413, b'{"error":"request body too large"}',
                              {"Content-Type": "application/json", **self._cors()})
        raw = self.rfile.read(n)
        path = self.path.rstrip("/")
        if path.endswith("/compress"):
            try:
                result = handle_compress(json.loads(raw), _ENGINE)
            except Exception as e:
                return self._send(400, json.dumps({"error": str(e)}).encode(), self._cors())
            return self._send(200, json.dumps(result).encode(),
                              {"Content-Type": "application/json", **self._cors()})
        is_anthropic = path.endswith("/messages")
        is_openai = path.endswith("/chat/completions")
        if not (is_anthropic or is_openai):
            return self._send(404, b'{"error":"only /v1/chat/completions or /v1/messages"}',
                              {"Content-Type": "application/json"})
        try:
            req = json.loads(raw)
            if is_anthropic:
                new_req, meta = transform_anthropic_request(req, _ENGINE)
            else:
                new_req, meta = transform_chat_request(req, _ENGINE)
        except Exception as e:
            return self._send(400, json.dumps({"error": str(e)}).encode())

        fwd_headers = {"Content-Type": "application/json"}
        if self.headers.get("Authorization"):
            fwd_headers["Authorization"] = self.headers.get("Authorization")
        for h in ("x-api-key", "anthropic-version", "anthropic-beta", "OpenAI-Organization"):
            if self.headers.get(h):
                fwd_headers[h] = self.headers.get(h)
        up = urllib.request.Request(_UPSTREAM + self.path,
                                    data=json.dumps(new_req).encode(), headers=fwd_headers)
        saved_hdrs = {"X-TRL-Tokens-Saved": str(meta["tokens_saved"]),
                      "X-TRL-Tokens-Before": str(meta["tokens_before"]),
                      "X-TRL-Tokens-After": str(meta["tokens_after"])}
        streaming = False
        try:
            with urllib.request.urlopen(up, timeout=300) as r:
                if new_req.get("stream"):
                    # stream the upstream SSE response through, unchanged
                    streaming = True
                    self.send_response(r.status)
                    self.send_header("Content-Type",
                                     r.headers.get("Content-Type", "text/event-stream"))
                    for k, v in saved_hdrs.items():
                        self.send_header(k, v)
                    self.end_headers()
                    while True:
                        chunk = r.read(2048)
                        if not chunk:
                            break
                        self.wfile.write(chunk); self.wfile.flush()
                else:
                    body = r.read()
                    self._send(r.status, body, {"Content-Type": "application/json", **saved_hdrs})
        except urllib.error.HTTPError as e:
            self._send(e.code, e.read())
        except Exception as e:
            if streaming:
                # headers already sent mid-stream; a second status line would
                # corrupt the response -- just drop the connection.
                self.close_connection = True
                return
            self._send(502, json.dumps({"error": f"upstream: {e}"}).encode())

    def log_message(self, *a):   # quiet
        pass


def main(port=None):
    if port is None:   # honor TRL_PORT for the pip-installed `trl-proxy` script too
        port = int(os.environ.get("TRL_PORT", "8899"))
    print(f"TRL proxy on http://localhost:{port}  ->  {_UPSTREAM}")
    print("point your client base_url at  http://localhost:%d/v1  (key unchanged)" % port)
    ThreadingHTTPServer(("127.0.0.1", port), Handler).serve_forever()


if __name__ == "__main__":
    main()
