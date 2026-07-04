"""Compare embedder options for retrieval recall on VAGUE queries against THIS
project's real code. Answers: does a stronger/retrieval-tuned embedder actually
beat keyword-only (the v0.6 negative was with potion-base-8M)? Runs on a machine
with internet (downloads the models). No API needed."""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from trl.retrieval import build_index, retrieve

CASES = [
    ("how do we avoid losing important numbers when shrinking text?", "_preserve_facts"),
    ("how do we pick which code to show the model instead of everything?", "retrieve"),
    ("how do we decide whether an easy request can skip the expensive model?", "cascade"),
    ("how big is a piece of text for the model?", "count_tokens"),
    ("how do we split a long document into pieces?", "chunk_document"),
    ("how do we combine caching, compression and retrieval on one request?", "process"),
    ("how do we talk to the small local model to summarize?", "summarize"),
]

MODELS = ["minishlab/potion-base-8M", "minishlab/potion-retrieval-32M"]


def recall(idx, embedder):
    hits = 0
    for q, want in CASES:
        idx.pop("_emb", None)
        got = {s.name for s in retrieve(idx, q, k=5, rerank=embedder is not None,
                                        embedder=embedder)["symbols"]}
        hits += want in got
    return hits


def main():
    idx = build_index(".")
    n = len(CASES)
    print(f"queries: {n}\n")
    print(f"  keyword-only              recall@5 = {recall(idx, None)}/{n}")
    for m in MODELS:
        try:
            from model2vec import StaticModel
            mod = StaticModel.from_pretrained(m)
            emb = lambda texts, _m=mod: [list(map(float, v)) for v in _m.encode(list(texts))]
            print(f"  {m:38s} recall@5 = {recall(idx, emb)}/{n}")
        except Exception as e:
            print(f"  {m:38s} FAILED: {type(e).__name__}: {str(e)[:80]}")
    print("DONE")


if __name__ == "__main__":
    main()
