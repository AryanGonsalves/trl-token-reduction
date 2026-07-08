"""Server-level hardening: request-body cap (413), scoped CORS (no wildcard), and
an end-to-end trace of the browser extension's /compress path. Starts the real
handler on an ephemeral localhost port; no external network."""
import sys, os, socket, threading, http.client, json
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from http.server import ThreadingHTTPServer
import proxy.server as S


def _serve():
    srv = ThreadingHTTPServer(("127.0.0.1", 0), S.Handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv, srv.server_address[1]


def test_body_cap_returns_413():
    srv, port = _serve()
    try:
        c = socket.create_connection(("127.0.0.1", port), timeout=5)
        # huge Content-Length, no body -> must 413 BEFORE trying to read the body
        c.sendall(b"POST /v1/chat/completions HTTP/1.1\r\nHost: x\r\n"
                  b"Content-Length: 20000000\r\n\r\n")
        line = c.recv(256).decode("latin1").split("\r\n")[0]
        c.close()
        assert "413" in line, line
    finally:
        srv.shutdown()


def _options_allow_origin(port, origin):
    conn = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
    conn.request("OPTIONS", "/compress", headers={"Origin": origin})
    r = conn.getresponse(); r.read()
    ao = r.getheader("Access-Control-Allow-Origin")
    conn.close()
    return ao


def test_cors_blocks_arbitrary_website():
    srv, port = _serve()
    try:
        # a random website gets NO Allow-Origin (and definitely not "*")
        assert _options_allow_origin(port, "https://evil.example") in (None, "")
    finally:
        srv.shutdown()


def test_cors_allows_extension_and_claude():
    srv, port = _serve()
    try:
        ext = "chrome-extension://abcdefghijklmnopabcdefghijklmnop"
        assert _options_allow_origin(port, ext) == ext
        assert _options_allow_origin(port, "https://claude.ai") == "https://claude.ai"
    finally:
        srv.shutdown()


def test_extension_compress_path_still_works():
    # Trace the actual extension flow: POST /compress from a chrome-extension
    # origin -> 200, scoped CORS echoed, compression happens, fact preserved.
    srv, port = _serve()
    try:
        ext = "chrome-extension://abcdefghijklmnopabcdefghijklmnop"
        text = "\n".join(["filler line here"] * 60) + "\namount 4821"
        body = json.dumps({"text": text, "mode": "compress"})
        conn = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
        conn.request("POST", "/compress", body=body,
                     headers={"Content-Type": "application/json", "Origin": ext})
        r = conn.getresponse()
        data = json.loads(r.read())
        conn.close()
        assert r.status == 200
        assert r.getheader("Access-Control-Allow-Origin") == ext
        assert "compressed" in data and "4821" in data["compressed"]  # fact kept
    finally:
        srv.shutdown()
