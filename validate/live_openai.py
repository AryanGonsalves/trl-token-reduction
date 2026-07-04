"""Live end-to-end validation vs REAL OpenAI. Three checks, each: does the model
give the RIGHT answer from the reduced context, and how many BILLED tokens/calls
did we save. Needs OPENAI_API_KEY. Cheap (a handful of gpt-4o-mini calls)."""
import os, re, sys, tempfile, random
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from openai import OpenAI
from trl import Engine
from trl.util import load_config, count_tokens
from trl.retrieval import build_text_index, retrieve_text
from proxy.transform import transform_chat_request

MODEL = os.environ.get("MODEL", "gpt-4o-mini")
_client = None
def _c():
    global _client
    if _client is None:
        _client = OpenAI(timeout=30, max_retries=3)
    return _client

def ask(messages):
    r = _c().chat.completions.create(model=MODEL, messages=messages,
                                     max_tokens=16, temperature=0)
    return (r.choices[0].message.content or "").strip(), r.usage.prompt_tokens


def check_compression():
    print("\n[1] COMPRESSION (bloated turn: naive vs proxy-transformed)")
    noise = "\n".join(['{"note":"no action required","trace":"span"}'] * 30)
    msgs = [{"role": "system", "content": "You are a finance agent. " * 40},
            {"role": "user", "content": "Batch:\n" + noise + '\n  "amount_usd": 7391,\n' + noise},
            {"role": "assistant", "content": "Loaded. " * 12},
            {"role": "user", "content": "What is amount_usd? integer only."}]
    ab, tb = ask(msgs)
    cfg = load_config("config.yaml"); cfg["local_model"]["provider"] = "mock"
    nr, _ = transform_chat_request({"model": MODEL, "messages": msgs}, Engine(cfg))
    ap, tp = ask(nr["messages"])
    print(f"    billed tokens {tb} -> {tp} ({100*(1-tp/tb):.0f}% less); "
          f"answers {ab!r}/{ap!r} correct={'7391' in ab and '7391' in ap}")


def _doc():
    rng = random.Random(7); facts = {}; secs = []
    topics = ["authentication","billing","shipping","privacy","analytics",
              "encryption","backups","scaling","logging","quotas"]
    for i in range(30):
        t = f"{topics[i%len(topics)]}_module_{i}"; code = rng.randint(1000,9999); facts[t]=code
        secs.append(f"SECTION {i}: {t}\nRoutine prose describing the {t} subsystem with "
                    f"lots of background nobody needs. The reference code for {t} is {code}. "
                    f"More narration that adds no facts.")
    return "\n\n".join(secs), facts


def check_doc_retrieval():
    print("\n[2] DOCUMENT RETRIEVAL (whole doc vs retrieved passages, real model)")
    doc, facts = _doc()
    idx = build_text_index({"handbook.txt": doc})
    topic = list(facts)[13]; gold = str(facts[topic])
    q = f"What is the reference code for {topic}? Reply with only the integer."
    ab, tb = ask([{"role": "user", "content": doc + "\n\n" + q}])
    r = retrieve_text(idx, q, token_budget=300, k=3, rerank=False)
    ap, tp = ask([{"role": "user", "content": r["context"] + "\n\n" + q}])
    print(f"    billed tokens {tb} -> {tp} ({100*(1-tp/tb):.0f}% less); "
          f"answers {ab!r}/{ap!r} correct={gold in ab and gold in ap}")


def check_cascade():
    print("\n[3] CASCADE (easy answered locally = $0; hard escalated to real model)")
    doc, facts = _doc()
    idx = build_text_index({"handbook.txt": doc})
    rng = random.Random(1)
    tasks = []
    for t in rng.sample(list(facts), 8):                       # easy lookups
        tasks.append((f"reference code for {t}", str(facts[t]), "easy"))
    tasks.append(("the single largest reference code in the whole handbook",
                  str(max(facts.values())), "hard"))
    big_calls = 0; correct = 0
    for q, gold, kind in tasks:
        m = re.search(r"code for (\w+)", q)
        local = None
        if m:
            topic = m.group(1)
            r = retrieve_text(idx, "reference code for " + topic, token_budget=300, k=2, rerank=False)
            hit = re.search(re.escape(topic) + r"\D*?is (\d+)", r["context"])
            local = hit.group(1) if hit else None
        if local is not None:                                   # confident local -> $0
            correct += (local == gold)
        else:                                                   # escalate to real model
            big_calls += 1
            ans, _ = ask([{"role": "user", "content": doc + "\n\n" + q + " Reply only the integer."}])
            correct += (gold in ans)
    print(f"    {len(tasks)} tasks: big-model calls used = {big_calls}/{len(tasks)} "
          f"({100*(1-big_calls/len(tasks)):.0f}% skipped locally); accuracy {100*correct/len(tasks):.0f}%")


def main():
    print(f"model: {MODEL}")
    check_compression()
    check_doc_retrieval()
    check_cascade()
    print("\nDONE")


if __name__ == "__main__":
    main()
