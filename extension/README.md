# TRL Composer (browser extension, v0)

Compresses the text in the Claude.ai composer **before you send it**, so you burn
fewer tokens against your subscription bucket. Manual + preview-first: you click
**⚡ Compress**, review the result (with a "numbers preserved" badge), then choose
to use it or keep your original. Nothing sends automatically.

## Why this and not a proxy
The Claude.ai web app talks to a fixed backend you can't redirect, and its cap is
token/compute-metered. You can't intercept its traffic legitimately — but you *can*
choose to type fewer tokens. This edits only your own composer text, in your own
session, with your consent. No traffic interception, no backend impersonation.

## Run it
1. Start the local engine (does the actual compressing + number-guard):
   ```
   python -m proxy.server        # serves POST http://localhost:8899/compress
   ```
2. Load the extension (Chrome/Edge): `chrome://extensions` → enable **Developer mode**
   → **Load unpacked** → select this `extension/` folder.
3. Open claude.ai. Paste a long doc into the message box, click **⚡ Compress**,
   review, **Use compressed**, then send as usual.

## Scope / honesty
- Helps most when you paste **large** context; short chats gain little.
- Compresses **your own input** (lossier than compressing history) — hence the
  mandatory preview and the number-guard.
- Stretches **Claude** caps (token-metered). Not useful for ChatGPT chat (per-message).
- v0 is a manual button. Send-key interception is a later, optional step.

## Configure the endpoint (optional)
Defaults to `http://localhost:8899/compress`. To change it, set
`chrome.storage.local` key `trl_endpoint` (a small options page comes later).

## If the button says "engine isn't running"
The extension talks to the local engine at `http://localhost:8899`. If it's not up,
you'll get a clear message telling you to run `trl-proxy` (or `python -m proxy.server`).
There's a `GET /health` you can check in a browser: `http://localhost:8899/health`.

## Zero-install mode (v0.1.0)
The extension now works with **no server at all** — it compresses in your browser
(dedupe + boilerplate removal, with the number-guard). Running the local engine
(`trl-proxy`) is optional and gives stronger compression; when it's not running,
the built-in compressor is used automatically. This is what makes the Chrome Web
Store version usable by non-technical people with a single click.

## Developer mode: stronger local engine (optional)
The Chrome Web Store build is pure zero-install (compresses in the browser). If you
want the stronger engine-backed compression, run it unpacked and add
`"http://localhost:8899/*"` back to `host_permissions` in manifest.json, then run
`trl-proxy`. Regular users never need this.
