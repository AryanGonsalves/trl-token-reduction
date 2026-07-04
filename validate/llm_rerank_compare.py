"""Does LLM-rerank beat keyword on vague code queries? Uses OPENAI_API_KEY (cheap:
7 short gpt-4o-mini calls). Compares recall@5: keyword-only vs LLM-reranked."""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from openai import OpenAI
from trl.retrieval import build_index, retrieve
from trl.retrieval.llm_rerank import llm_rerank

MODEL = os.environ.get("MODEL", "gpt-4o-mini")
_c = OpenAI(timeout=30, max_retries=2)
def ask(prompt):
    r = _c.chat.completions.create(model=MODEL, max_tokens=40, temperature=0,
                                   messages=[{"role": "user", "content": prompt}])
    return r.choices[0].message.content or ""

CASES = [
    ("how do we avoid losing important numbers when shrinking text?", "_preserve_facts"),
    ("how do we pick which code to show the model instead of everything?", "retrieve"),
    ("how do we decide whether an easy request can skip the expensive model?", "cascade"),
    ("how big is a piece of text for the model?", "count_tokens"),
    ("how do we split a long document into pieces?", "chunk_document"),
    ("how do we combine caching, compression and retrieval on one request?", "process"),
    ("how do we talk to the small local model to summarize?", "summarize"),
]

def main():
    idx = build_index(".")
    syms = idx["symbols"]
    kw = llm = 0
    for q, want in CASES:
        kw_hit = want in {s.name for s in retrieve(idx, q, k=5, rerank=False)["symbols"]}
        llm_hit = want in {s.name for s in llm_rerank(q, syms, 5, ask, shortlist=len(syms))}
        kw += kw_hit; llm += llm_hit
        print(f"  {'kw:'+('Y' if kw_hit else 'n'):5s} {'llm:'+('Y' if llm_hit else 'n'):6s} {q[:52]}")
    n = len(CASES)
    print(f"\nRECALL@5  keyword-only: {kw}/{n}   LLM-rerank: {llm}/{n}")
    print("DONE")

if __name__ == "__main__":
    main()
