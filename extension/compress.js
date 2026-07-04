// Pure-JS token-reduction fallback so the extension works with NO local server.
// Ports the engine's heuristic compressor + fact-guard. Weaker than the local
// engine (it has no summarizer model), but zero-install: it dedupes repeated
// lines and drops boilerplate, and the fact-guard guarantees every number
// survives. Loaded before content.js; exposes window.__trlLocalCompress.
(function () {
  "use strict";

  const BOILERPLATE = ["DEBUG", "TRACE", "INFO:", 'File "', "Traceback (most recent", "at "];
  const isBoilerplate = (s) => BOILERPLATE.some((p) => s.startsWith(p));

  function heuristicCompress(text) {
    const seen = new Set();
    const out = [];
    for (const line of text.split("\n")) {
      const s = line.trim();
      if (!s || seen.has(s) || isBoilerplate(s)) continue;
      seen.add(s);
      out.push(line);
    }
    return out.join("\n");
  }

  const nums = (s) => (s.replace(/,/g, "").match(/-?\d+/g) || []);

  // Deterministic safety net: guarantee every number in `original` survives.
  function preserveFacts(original, compressed) {
    const comp = new Set(nums(compressed));
    const seen = new Set();
    const add = [];
    for (const line of original.split("\n")) {
      if (nums(line).some((n) => !comp.has(n))) {
        const key = line.trim();
        if (key && !seen.has(key) && !compressed.includes(key)) { seen.add(key); add.push(key); }
      }
    }
    return add.length ? compressed + "\n" + add.join("\n") : compressed;
  }

  const estTokens = (s) => Math.max(1, Math.ceil(s.length / 4)); // rough, no tiktoken in-browser

  window.__trlLocalCompress = function (text) {
    let out = preserveFacts(text, heuristicCompress(text));
    if (out.length >= text.length) out = text; // never expand
    const before = estTokens(text), after = estTokens(out);
    return {
      compressed: out,
      tokens_before: before,
      tokens_after: after,
      saved_pct: before ? Math.round((1 - after / before) * 1000) / 10 : 0,
      preserved_facts: Array.from(new Set(nums(text))).sort((a, b) => a.length - b.length),
      approx: true,
      engine: "builtin",
    };
  };
})();
