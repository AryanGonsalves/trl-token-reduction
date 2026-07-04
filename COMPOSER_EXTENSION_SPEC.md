# Composer-Compression Extension — Spec

**Working name:** TRL Composer
**Goal:** cut the tokens a subscription client *sends* — before it sends them —
so token-metered caps (Claude, Codex) stretch further. Reuses the existing
`compress` + fact-guard + retrieval engine unchanged. No traffic interception,
no backend impersonation: it only edits the user's own composer text, in the
user's own session, with the user's consent.

## 1. Where it applies (and why, per real metering)

| Target | Metering | Extension value |
|--------|----------|-----------------|
| **claude.ai web** | token/compute bucket, shared across Claude Code + claude.ai + Cowork | **Primary.** Fewer tokens in = real cap headroom. |
| **chatgpt.com web** | per-message (5-hr rolling) | Secondary. Compression doesn't add messages; only helps fit long docs in context. |
| **Codex / Claude Code** | token-metered subs (Codex realigned to API-token billing Apr 2026) | **Already covered by the MCP plugin** — no extension needed. |

So the extension exists mainly for the ONE surface we can't reach any other
legitimate way: the Claude.ai chat box.

## 2. Architecture

Browser extension (Manifest V3) + the existing engine exposed over localhost.

```
claude.ai composer ──(content script)──► POST http://localhost:8899/compress
                                             │  (existing engine:
                                             │   compress_request + _preserve_facts
                                             │   OR build_text_index/retrieve_text)
   preview panel ◄───{compressed, tokens_before/after, preserved_facts[]}───┘
        │ user: Send compressed / Send original / Edit
        ▼
   inject compressed text into composer, let Claude.ai send it
```

**Two build options, phased:**
- **Phase 1 (recommended): local-engine.** Add one endpoint `POST /compress` to
  `proxy/server.py`. The extension calls it. Pro: reuses the *exact* fact-guard and
  retrieval — the crown jewels — no reimplementation. Con: user runs a local process
  (same one that already powers the proxy).
- **Phase 2 (optional): JS heuristic fallback** ported into the extension for
  zero-install, using `heuristic_compress` logic only (no local summarizer model).
  Weaker, but works with nothing running.

## 3. New engine endpoint (small, reuses everything)

`POST /compress`
```json
// request
{ "text": "<pasted bulk context>", "question": "<optional live ask>",
  "mode": "compress" }         // or "retrieve" for doc-slice mode
// response
{ "compressed": "…", "tokens_before": 5120, "tokens_after": 1490,
  "saved_pct": 70.9, "preserved_facts": ["300", "2026-04-02", "v5.5"] }
```
Wraps `compress_request` + `_preserve_facts` (+ `count_tokens`) for `mode:compress`,
and `build_text_index`/`retrieve_text` for `mode:retrieve`. All already built and tested.

## 4. Hooking the input box (claude.ai = ProseMirror contenteditable)

- Content script locates the composer via a resilient selector + `MutationObserver`
  (feature-detect, don't hard-code fragile classes).
- **v0 (safest): a "Compress" button** injected next to the composer. User clicks it →
  text goes to `/compress` → preview → on accept, replace composer content. No send
  interception at all. Ship this first.
- **v1 (optional): intercept send** — capture-phase listener on Enter (no Shift) and the
  send button; `preventDefault`; run compress → preview → dispatch the real send.
- **Golden rule (mirrors the engine):** only compress the *pasted bulk context*; never
  the user's short live instruction. Heuristic: compress blocks over ~N tokens / pasted
  doc text; leave typed one-liners untouched. Never touch attachments, images, or code
  fences.

## 5. Pre-send preview (the trust surface — non-negotiable)

Because this compresses the user's *own* input (lossier than compressing history):
- Diff panel: `5,120 → 1,490 tokens (−71%)`, compressed text **editable**.
- **"Numbers preserved" badge** listing the protected values from the fact-guard.
- Choices: **Send compressed / Send original / Edit**.
- Setting: `always preview` (default) vs `auto-send`. Persist locally.

## 6. ToS & safety (why this is legitimate)

- Operates only on the user's own composer text, in their own authenticated session;
  the user chooses to send fewer tokens. No MITM, no reading traffic, no calling private
  backends, no impersonating an official client.
- Never auto-submits without consent (preview default on). Never touches cookies, auth,
  attachments. Nothing leaves the machine (engine runs on localhost).

## 7. Milestones

1. `POST /compress` on the existing engine. *(small)*
2. MV3 skeleton + content script finds composer + manual **Compress button** (no send hook). *(v0 shippable)*
3. Preview panel + fact badge.
4. Optional: Enter/send interception for a one-key flow.
5. Optional: JS heuristic fallback (zero-install).

## 8. Honest limits

- Only helps when you paste **large** context; short chats gain little — say so.
- Lossy on your own content; mitigated by preview + fact-guard, not eliminated. Aggressive
  mode stays off by default.
- Depends on claude.ai's DOM; keep the hook defensive.
- Does **not** stretch ChatGPT *chat* caps (per-message). Does **not** intercept API traffic.
