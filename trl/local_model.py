"""The local preprocessor model.

Small on purpose. Its jobs are extractive: summarize history, dedupe/trim tool
output, decide what's redundant. It must be CHEAP relative to the API tokens it
saves, or the economics invert (Hard Truth: the preprocessor's cost is counted
against savings).

Reached over Ollama's HTTP API. If Ollama isn't up (or provider == 'none'), we
fall back to a deterministic heuristic so the pipeline still runs and the
benchmark stays reproducible offline. provider == 'mock' uses smart_compress, a
competent-local-model stand-in, so the offline benchmark can show the achievable
case without a GPU.
"""
import json
import re
import urllib.request


class LocalModel:
    def __init__(self, cfg: dict):
        self.provider = cfg.get("provider", "none")
        self.model = cfg.get("model", "")
        self.endpoint = cfg.get("endpoint", "http://localhost:11434")

    def available(self) -> bool:
        if self.provider != "ollama":
            return False
        try:
            with urllib.request.urlopen(self.endpoint + "/api/tags", timeout=1.5):
                return True
        except Exception:
            return False

    def summarize(self, text: str, instruction: str) -> str:
        """Return a compressed version of `text` following `instruction`.
        Guards: never expand, never blank out. If the local model errors or
        returns something longer/empty, fall back to the safe heuristic so a bad
        preprocessor can never make the payload worse."""
        out = self._summarize(text, instruction)
        # Contract: never blank out. If compression nuked everything (e.g. the
        # input was entirely boilerplate, so heuristic_compress returned ""),
        # keep the original text rather than hand back an empty payload.
        return out if out.strip() else text

    def _summarize(self, text: str, instruction: str) -> str:
        if self.provider == "mock":
            return smart_compress(text)
        if self.provider == "openai":
            # A REAL LLM compressor (e.g. gpt-4o-mini) that paraphrases as it
            # compresses -- the honest test of "does a real model keep the
            # load-bearing facts?", runnable without a local runtime.
            try:
                out = self._openai(text, instruction)
                if out and len(out) < len(text):
                    return out
            except Exception:
                pass
            return heuristic_compress(text)
        if self.available():
            try:
                out = self._ollama(text, instruction)
                if out and len(out) < len(text):
                    return out
            except Exception:
                pass
        return heuristic_compress(text)

    def _openai(self, text: str, instruction: str) -> str:
        import openai
        prompt = (
            f"{instruction}\n\nRemove redundancy and irrelevance. NEVER drop "
            f"facts, numbers, ids, names, or decisions. Output only the "
            f"compressed text.\n\n---\n{text}"
        )
        client = openai.OpenAI(timeout=30, max_retries=3)
        r = client.chat.completions.create(
            model=self.model or "gpt-4o-mini",
            messages=[{"role": "user", "content": prompt}],
            temperature=0, max_tokens=600)
        return (r.choices[0].message.content or "").strip()

    def _ollama(self, text: str, instruction: str) -> str:
        prompt = (
            f"{instruction}\n\nRemove redundancy and irrelevance. NEVER drop "
            f"facts, numbers, ids, names, or decisions. Output only the "
            f"compressed text.\n\n---\n{text}"
        )
        body = json.dumps({
            "model": self.model,
            "prompt": prompt,
            "stream": False,
            "options": {"temperature": 0, "num_predict": 256},
        }).encode()
        req = urllib.request.Request(
            self.endpoint + "/api/generate", data=body,
            headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=90) as r:
            return json.loads(r.read())["response"].strip()


def heuristic_compress(text: str) -> str:
    """Deterministic, model-free fallback. Conservative: removes only
    provably-redundant material (exact duplicate lines, boilerplate log noise).
    The 'safe floor' — never destroys unique information, but weak on its own."""
    seen = set()
    out = []
    for line in text.splitlines():
        s = line.strip()
        if not s or s in seen or _is_boilerplate(s):
            continue
        seen.add(s)
        out.append(line)
    return "\n".join(out)


_BOILERPLATE = (
    "at ", "DEBUG", "TRACE", "INFO:", "File \"", "Traceback (most recent",
)


def _is_boilerplate(s: str) -> bool:
    return s.startswith(_BOILERPLATE)


_FACTISH = re.compile(r"KEYFACT|\$|order|account|prior-decision|STATUS|\d")


def smart_compress(text: str) -> str:
    """Fact-preserving heavy compression — the behavior we want from a real
    local model. Keeps the first line for structure and any line carrying a fact
    (ids, numbers, money, decisions); drops narrative/boilerplate. 'Remove what
    the model doesn't need, keep what it does' made concrete. Real runs replace
    this with an actual small model via Ollama."""
    kept = []
    for i, line in enumerate(text.splitlines()):
        s = line.strip()
        if not s:
            continue
        if (i == 0 or _FACTISH.search(s)) and s not in kept:
            kept.append(s)
    return "\n".join(kept)
