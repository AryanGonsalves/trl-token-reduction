"""Sweep the retrieval reranker's `min_similarity` floor against THIS repo's real
code using a REAL static embedder (model2vec). Answers the open question from the
P2 fix: does the default 0.10 floor preserve recall on vague queries while
rejecting unrelated-query noise, and is there a better value?

No API keys, no cost -- downloads the embedding model once. Run on a machine with
internet. Reads nothing secret; safe to commit the script (results are gitignored
via *_result.txt).
"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from trl.retrieval import build_index, retrieve

# vague, keyword-poor questions -> the symbol that really answers them.
# Recall here is what we must NOT hurt with the floor.
CASES = [
    ("how do we avoid losing important numbers when shrinking text?", "_preserve_facts"),
    ("how do we pick which code to show the model instead of everything?", "retrieve"),
    ("how do we decide whether an easy request can skip the expensive model?", "cascade"),
    ("how big is a piece of text for the model?", "count_tokens"),
    ("how do we combine caching, compression and retrieval on one request?", "process"),
    ("how do we talk to the small local model to summarize?", "summarize"),
]

# Off-topic queries with NO real answer in this codebase. A good floor drives the
# number of returned slices toward 0 (fewer wasted tokens on noise).
NOISE = [
    "what is the airspeed velocity of an unladen swallow",
    "recipe for sourdough bread starter overnight",
    "how tall is mount everest in meters",
    "best hiking trails near the pacific coast",
]

THRESHOLDS = [0.0, 0.05, 0.10, 0.15, 0.20, 0.30]


def _names(idx, q, emb, thr, k=5):
    idx.pop("_emb", None)
    return {s.name for s in retrieve(idx, q, k=k, rerank=emb is not None,
                                     embedder=emb, min_similarity=thr)["symbols"]}


def recall_at(idx, emb, thr, k=5):
    return sum(want in _names(idx, q, emb, thr, k) for q, want in CASES)


def noise_slices(idx, emb, thr, k=5):
    total = 0
    for q in NOISE:
        idx.pop("_emb", None)
        total += len(retrieve(idx, q, k=k, rerank=emb is not None,
                              embedder=emb, min_similarity=thr)["symbols"])
    return total / len(NOISE)


def run(idx, emb):
    n = len(CASES)
    idx.pop("_emb", None)
    kw = sum(want in {s.name for s in retrieve(idx, q, k=5, rerank=False)["symbols"]}
             for q, want in CASES)
    print(f"cases: {n}   keyword-only recall@5: {kw}/{n}\n")
    print(f"{'min_sim':>8} {'recall@5':>10} {'noise_slices@5':>16}")
    rows = []
    for thr in THRESHOLDS:
        r = recall_at(idx, emb, thr)
        ns = noise_slices(idx, emb, thr)
        rows.append((thr, r, ns))
        print(f"{thr:8.2f} {r:>7}/{n} {ns:>16.2f}")
    best = max(rows, key=lambda x: (x[1], -x[2]))
    print(f"\nHighest recall with least noise at min_sim={best[0]:.2f} "
          f"(recall {best[1]}/{n}, noise {best[2]:.2f} slices).")
    print("Rule: keep the LARGEST min_sim that still holds max recall, to cut noise.")
    return rows


def main():
    from trl.retrieval.embed import get_embedder
    idx = build_index(".")
    emb = get_embedder()
    print("embedder loaded:", emb is not None)
    if emb is None:
        print("NO embedder -- `pip install model2vec` and allow the model to download.")
        return
    run(idx, emb)
    print("DONE")


if __name__ == "__main__":
    main()
