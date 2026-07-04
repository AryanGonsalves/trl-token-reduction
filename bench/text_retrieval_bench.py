"""Document-QA benchmark: text retrieval vs stuffing the whole document.

A large multi-section document with a distinct fact buried in each section. For
each question we compare: baseline = whole document in context; treatment = only
the retrieved passages. Measures token reduction + whether the answer survived.
Deterministic, offline. This is the CODE-QA benchmark's prose sibling -- proof the
retrieval lever works for general text (docs / PDFs / knowledge bases), not code."""
import os, random, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from trl.retrieval import build_text_index, retrieve_text
from trl.util import count_tokens
from bench.stats import noninferiority

_TOPICS = ["authentication", "billing", "shipping", "privacy", "support",
           "analytics", "compliance", "onboarding", "storage", "networking",
           "encryption", "backups", "monitoring", "scaling", "caching",
           "logging", "permissions", "quotas", "webhooks", "migrations"]


def _make_doc(n_sections=40, seed=7):
    rng = random.Random(seed)
    facts = {}
    secs = []
    for i in range(n_sections):
        topic = f"{_TOPICS[i % len(_TOPICS)]}_module_{i}"
        code = rng.randint(1000, 9999)
        facts[topic] = code
        secs.append(
            f"SECTION {i}: {topic.replace('_', ' ').title()}\n"
            f"This section documents the {topic} subsystem. It contains routine "
            f"operational prose that most readers skim past, describing standard "
            f"procedures, edge cases, and historical context nobody needs day to day. "
            f"The reference code for {topic} is {code}. "
            f"Further narration continues with additional background that adds no new facts.")
    return "\n\n".join(secs), facts


def run(n_tasks=24, seed=7):
    rng = random.Random(seed)
    doc, facts = _make_doc(seed=seed)
    idx = build_text_index({"handbook.txt": doc})
    whole = count_tokens(doc)
    targets = rng.sample(list(facts), n_tasks)
    rows = []
    for topic in targets:
        q = f"What is the reference code for {topic}?"
        r = retrieve_text(idx, q, token_budget=350, k=3, rerank=False)
        ans = str(facts[topic])
        rows.append({"b_ok": int(ans in doc), "t_ok": int(ans in r["context"]),
                     "b_tok": whole, "t_tok": r["tokens"]})
    n = len(rows)
    b = sum(r["b_tok"] for r in rows) / n
    t = sum(r["t_tok"] for r in rows) / n
    ni = noninferiority([r["b_ok"] for r in rows], [r["t_ok"] for r in rows], 0.01, seed=seed)
    print("=" * 66)
    print(" DOCUMENT-QA BENCHMARK  text retrieval vs whole-document dump")
    print("=" * 66)
    print(f" doc: {len(facts)} sections, {whole} tokens; {len(idx['chunks'])} chunks; {n} questions")
    print(f" context tokens/task:  {b:.0f} (whole doc) -> {t:.0f} (retrieved)"
          f"   ({100*(1-t/b):.1f}% less, {b/max(t,1):.1f}x)")
    print(f" quality (answer present): baseline {ni['baseline_success']*100:.0f}% -> "
          f"retrieval {ni['treatment_success']*100:.0f}%  "
          f"({'PASS' if ni['non_inferior'] else 'FAIL'})")
    print("=" * 66)
    return {"mult": b / max(t, 1), "ni": ni}


if __name__ == "__main__":
    run()
