"""Ollama smoke test — run on YOUR machine once Ollama is up:
    ollama serve &                    # if not already running
    ollama pull qwen2.5:7b-instruct
    python tests/test_ollama_smoke.py

Checks: (1) the endpoint is reachable, (2) compression actually shrinks a
bloated tool output, (3) the load-bearing fact SURVIVES (the whole point)."""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from trl.local_model import LocalModel

SAMPLE = "\n".join(
    ['{', '  "object": "transaction",']
    + ['  "note": "no action required for this record",'] * 20
    + ['  "amount_usd": 742,']
    + ['  "trace": "span opened; span closed",'] * 20 + ['}'])

def main():
    lm = LocalModel({"provider": "ollama", "model": os.environ.get("OLLAMA_MODEL", "llama3.2:3b"),
                     "endpoint": "http://localhost:11434"})
    if not lm.available():
        print("SKIP: Ollama not reachable at localhost:11434. Start it first.")
        return
    out = lm.summarize(SAMPLE, "Compress this raw tool output for re-use.")
    shrunk = len(out) < len(SAMPLE)
    fact_kept = "742" in out
    print(f"chars {len(SAMPLE)} -> {len(out)}  (shrunk={shrunk})")
    print(f"load-bearing fact 742 preserved: {fact_kept}")
    assert shrunk, "local model did not compress"
    assert fact_kept, "FACT DROPPED — this preprocessor is unsafe, do not ship it"
    print("OLLAMA SMOKE TEST PASSED")

if __name__ == "__main__":
    main()
