// TRL Composer v0 — a manual "Compress" button for the Claude.ai composer.
// No send interception: you click Compress, review a preview, then Accept to
// replace the composer text. You stay in control; nothing sends automatically.
// Works with no setup: if the local engine is running it's used (stronger),
// otherwise it falls back to the built-in in-browser compressor.

(function () {
  "use strict";

  // --- find the ProseMirror composer, resiliently -------------------------
  function findComposer() {
    const sels = [
      'div.ProseMirror[contenteditable="true"]',
      '[contenteditable="true"][role="textbox"]',
      'div[contenteditable="true"]',
    ];
    for (const s of sels) {
      const nodes = document.querySelectorAll(s);
      if (nodes.length) return nodes[nodes.length - 1]; // composer is last on page
    }
    return null;
  }

  function readText(el) { return (el.innerText || "").trim(); }

  // Replace composer content in a ProseMirror-friendly way.
  function writeText(el, text) {
    el.focus();
    const sel = window.getSelection();
    sel.selectAllChildren(el);
    let ok = false;
    try { ok = document.execCommand("insertText", false, text); } catch (_) {}
    if (!ok) {
      try {
        const dt = new DataTransfer();
        dt.setData("text/plain", text);
        el.dispatchEvent(new ClipboardEvent("paste", { clipboardData: dt, bubbles: true }));
        ok = true;
      } catch (_) {}
    }
    el.dispatchEvent(new Event("input", { bubbles: true }));
    return ok;
  }

  // --- floating button ----------------------------------------------------
  function makeButton() {
    if (document.getElementById("trl-fab")) return;
    const b = document.createElement("button");
    b.id = "trl-fab";
    b.type = "button";
    b.textContent = "⚡ Compress";
    b.title = "Compress the composer text before sending (TRL)";
    b.addEventListener("click", onCompress);
    document.body.appendChild(b);
  }

  // --- preview panel ------------------------------------------------------
  function showPreview(original, data, composer) {
    closePanel();
    const wrap = document.createElement("div");
    wrap.id = "trl-panel";
    const facts = (data.preserved_facts || []).slice(0, 40)
      .map((f) => `<span class="trl-chip">${escapeHtml(f)}</span>`).join("");
    // Coerce stats to numbers so nothing from the response is interpolated as HTML.
    const tokBefore = Number(data.tokens_before) || 0;
    const tokAfter = Number(data.tokens_after) || 0;
    const savedPct = Number(data.saved_pct) || 0;
    const approx = data.approx ? "~" : "";
    const engineNote = data.engine === "builtin"
      ? "Built-in compressor (dedupe + boilerplate). Run the local engine for stronger results."
      : "Compressed by the local engine.";
    wrap.innerHTML = `
      <div class="trl-head">
        <span>TRL Composer</span>
        <button id="trl-x" title="Close">✕</button>
      </div>
      <div class="trl-stats">
        <b>${approx}${tokBefore}</b> → <b>${approx}${tokAfter}</b> tokens
        <span class="trl-save">−${savedPct}%</span>
      </div>
      <textarea id="trl-out" spellcheck="false"></textarea>
      <div class="trl-facts">${facts ? "Numbers preserved: " + facts : ""}</div>
      <div class="trl-actions">
        <button id="trl-accept" class="trl-primary">Use compressed</button>
        <button id="trl-cancel">Keep original</button>
      </div>
      <div class="trl-note">${escapeHtml(engineNote)} Review it — nothing sends until you press Enter yourself.</div>`;
    document.body.appendChild(wrap);
    const out = wrap.querySelector("#trl-out");
    out.value = data.compressed;
    wrap.querySelector("#trl-x").onclick = closePanel;
    wrap.querySelector("#trl-cancel").onclick = closePanel;
    wrap.querySelector("#trl-accept").onclick = () => {
      writeText(composer, out.value);
      closePanel();
    };
  }

  function closePanel() {
    const p = document.getElementById("trl-panel");
    if (p) p.remove();
  }

  function escapeHtml(s) {
    return String(s).replace(/[&<>"']/g, (c) =>
      ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  }

  function toast(msg) {
    const t = document.createElement("div");
    t.className = "trl-toast";
    t.textContent = msg;
    document.body.appendChild(t);
    setTimeout(() => t.remove(), 4000);
  }

  // --- action -------------------------------------------------------------
  function onCompress() {
    const composer = findComposer();
    if (!composer) { toast("Couldn't find the message box."); return; }
    const text = readText(composer);
    if (text.length < 40) { toast("Nothing much to compress yet."); return; }
    const btn = document.getElementById("trl-fab");
    btn.disabled = true; btn.textContent = "… compressing";

    const useBuiltin = () => {
      const data = window.__trlLocalCompress(text); // zero-install, in-browser
      showPreview(text, data, composer);
    };
    chrome.runtime.sendMessage(
      { type: "trl_compress", payload: { text, mode: "compress" } },
      (resp) => {
        btn.disabled = false; btn.textContent = "⚡ Compress";
        // Prefer the local engine when running (stronger); else fall back so it
        // always works with no setup.
        if (chrome.runtime.lastError || !resp || !resp.ok ||
            !resp.data || resp.data.error) {
          useBuiltin(); return;
        }
        showPreview(text, resp.data, composer);
      }
    );
  }

  // --- keep the button present across SPA navigation ----------------------
  makeButton();
  const mo = new MutationObserver(() => { if (!document.getElementById("trl-fab")) makeButton(); });
  mo.observe(document.body, { childList: true, subtree: false });
})();
