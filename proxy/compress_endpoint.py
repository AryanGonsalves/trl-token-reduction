"""Local /compress endpoint for the composer-compression browser extension.

No upstream call. Takes the user's pasted bulk context, runs the SAME
compression + fact-guard (or the text retriever) the rest of the engine uses,
and returns the shorter text plus token counts and the numeric facts the guard
guarantees survived -- so the extension can show a trustworthy pre-send preview.

Isolated + pure so it unit-tests offline (like transform.py)."""
import re

from trl.message import Message, TOOL_RESULT
from trl.compress import compress_request
from trl.util import count_tokens

_NUM = re.compile(r"-?\d[\d,]*")


def handle_compress(req: dict, engine) -> dict:
    text = (req.get("text") or "").strip()
    if not text:
        return {"error": "no text"}
    mode = req.get("mode", "compress")
    question = (req.get("question") or "").strip()
    budget = int(req.get("budget", 1200))
    before = count_tokens(text)

    if mode == "retrieve":
        # Doc-slice mode: keep only the passages relevant to `question`.
        from trl.retrieval import build_text_index, retrieve_text
        idx = build_text_index({"pasted": text})
        r = retrieve_text(idx, question or text, token_budget=budget, rerank=False)
        out = r.get("context", "") or text
    else:
        # Compression mode: summarize the tail, then the deterministic fact-guard
        # re-injects any dropped number. Short text (<200 chars) passes through.
        msg = Message("tool", TOOL_RESULT, text)
        new_msgs, _ = compress_request([msg], engine.mode, engine.local)
        out = "\n".join(m.content for m in new_msgs).strip() or text

    after = count_tokens(out)
    preserved = sorted({n.replace(",", "") for n in _NUM.findall(text)}, key=len)
    return {
        "compressed": out,
        "tokens_before": before,
        "tokens_after": after,
        "saved_pct": round(100 * (1 - after / before), 1) if before else 0.0,
        "preserved_facts": preserved,
        "mode": mode,
    }
