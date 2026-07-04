"""Optional local embedder for semantic rerank. Tries model2vec (static, fast,
no torch), then sentence-transformers; returns None if neither is available so
retrieval falls back to keyword+call-graph only. Set TRL_EMBED_MODEL to override.

An embedder is just: callable(list[str]) -> list[list[float]]."""
import os


def get_embedder():
    name = os.environ.get("TRL_EMBED_MODEL", "")
    try:
        from model2vec import StaticModel
        model = StaticModel.from_pretrained(name or "minishlab/potion-retrieval-32M")
        return lambda texts: [list(map(float, v)) for v in model.encode(list(texts))]
    except Exception:
        pass
    try:
        from sentence_transformers import SentenceTransformer
        model = SentenceTransformer(name or "all-MiniLM-L6-v2")
        return lambda texts: [list(map(float, v)) for v in model.encode(list(texts))]
    except Exception:
        return None
