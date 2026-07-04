// Service worker: the ONLY thing that talks to the local engine. Content scripts
// message us; we fetch localhost (allowed via host_permissions, sidestepping the
// page's mixed-content/CORS rules) and return the result.
const ENDPOINT_KEY = "trl_endpoint";
const DEFAULT_ENDPOINT = "http://localhost:8899/compress";

async function endpoint() {
  try {
    const s = await chrome.storage.local.get(ENDPOINT_KEY);
    return s[ENDPOINT_KEY] || DEFAULT_ENDPOINT;
  } catch (_) { return DEFAULT_ENDPOINT; }
}

async function fetchWithTimeout(url, opts, ms) {
  const ctrl = new AbortController();
  const t = setTimeout(() => ctrl.abort(), ms);
  try { return await fetch(url, { ...opts, signal: ctrl.signal }); }
  finally { clearTimeout(t); }
}

const ENGINE_DOWN =
  "Local engine isn't running. Open a terminal and run:  trl-proxy  " +
  "(or: python -m proxy.server), then try again.";

chrome.runtime.onMessage.addListener((msg, _sender, sendResponse) => {
  if (msg && msg.type === "trl_compress") {
    (async () => {
      try {
        const url = await endpoint();
        const res = await fetchWithTimeout(url, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(msg.payload),
        }, 8000);
        if (!res.ok) { sendResponse({ ok: false, error: "Engine returned HTTP " + res.status }); return; }
        sendResponse({ ok: true, data: await res.json() });
      } catch (e) {
        const down = (e && (e.name === "AbortError" || String(e).includes("Failed to fetch")));
        sendResponse({ ok: false, error: down ? ENGINE_DOWN : ("Error: " + String(e)) });
      }
    })();
    return true; // async response
  }
});
