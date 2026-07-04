"""Real-embedder validation: does semantic rerank (model2vec) beat keyword-only
on VAGUE queries against THIS project's real code? Prints, per query, whether the
expected symbol is found keyword-only vs reranked. No API needed."""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from trl.retrieval import build_index, retrieve
from trl.retrieval.embed import get_embedder

# vague, keyword-poor questions -> the symbol that really answers them
CASES = [
    ("how do we avoid losing important numbers when shrinking text?", "_preserve_facts"),
    ("how do we pick which code to show the model instead of everything?", "retrieve"),
    ("how do we decide whether an easy request can skip the expensive model?", "cascade"),
    ("how big is a piece of text for the model?", "count_tokens"),
    ("how do we split a long document into pieces?", "chunk_document"),
]


def top(idx, q, embedder, k=5):
    return {s.name for s in retrieve(idx, q, k=k, rerank=embedder is not None,
                                     embedder=embedder)["symbols"]}


def main():
    idx = build_index(".")
    emb = get_embedder()
    print("embedder loaded:", emb is not None)
    if emb is None:
        print("NO embedder available -- install model2vec and ensure the model can download.")
        return
    kw_hits = rr_hits = 0
    for q, want in CASES:
        idx.pop("_emb", None)
        kw = top(idx, q, None)
        idx.pop("_emb", None)
        rr = top(idx, q, emb)
        k_ok, r_ok = want in kw, want in rr
        kw_hits += k_ok; rr_hits += r_ok
        print(f"Q: {q}\n   want '{want}'  keyword-only:{k_ok}  reranked:{r_ok}")
    n = len(CASES)
    print(f"\nRECALL@5  keyword-only: {kw_hits}/{n}   with embedding rerank: {rr_hits}/{n}")
    print("DONE")


if __name__ == "__main__":
    main()
