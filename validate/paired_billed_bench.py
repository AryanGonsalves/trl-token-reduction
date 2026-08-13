"""Paired, BILLED-token benchmark: does the trl-retrieve MCP actually cut real billed
input tokens in an agent loop, vs an agent that just uses shell (grep/sed/read)?

Runs the SAME tasks through a real tool-use agent loop twice:
  config "mcp"   : tools = retrieve_code(query), explain_symbol(name)   [the plugin]
  config "shell" : tools = bash(cmd) [read-only grep/sed/head/cat/rg], read_file(path,...)
and sums PROVIDER-BILLED usage.input_tokens over every turn (schemas + history + results).
Baseline is a competent shell agent, not "read the whole file" -- the fair test.

Every session is forced to a final answer (no silent truncation), and a grader call rates
both answers vs the reference code, so a token win can't hide a quality loss.

Prove offline first:  --fake  (no network).
Real run:  python -m validate.paired_billed_bench --repo D:\\RobloxShooter --model claude-sonnet-5
"""
import argparse, os, subprocess, sys, json, re
os.environ.setdefault("HF_HUB_DISABLE_PROGRESS_BARS", "1")
os.environ.setdefault("TRANSFORMERS_NO_ADVISORY_WARNINGS", "1")
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from trl.retrieval.ast_index import build_index
from trl.retrieval.retrieve import retrieve as trl_retrieve
from trl.util import count_tokens

PRICES = {  # USD / 1M tokens (input, output) -- only for the HARD cost cap guard
    "claude-haiku-4-5-20251001": (1.00, 5.00),
    "claude-sonnet-5": (3.00, 15.00),
    "claude-opus-5": (15.00, 75.00),
}
DEFAULT_MODEL = "claude-sonnet-5"

SYSTEM = ("You are a coding assistant answering a question about a codebase. Use the tools to "
          "find and read the relevant code, then give a short, correct answer. Be economical: "
          "fetch only what you need and stop and answer as soon as you can.")

TASKS = [
    "How does RaidService decide whether a raid succeeds, fails, or the defender escapes? Summarize the logic.",
    "In DataService, how is a player's profile loaded, and what happens on a session-lock conflict / retry?",
    "Where and how is a player's stash adjusted when they go offline, and which service does it?",
    "How does PlotService persist plot ownership so it survives a player rejoining?",
    "Trace how buying a boost in MonetizationService actually grants the boost (which functions/services are involved).",
    "How does the combat system validate a hit on the server side?",
]

MCP_TOOLS = [
    {"name": "retrieve_code",
     "description": ("Return the most relevant code slices for a question, instead of reading whole "
                     "files. Args: query (the question, REQUIRED string), k (max slices, default 8), "
                     "budget (token budget, default 1200). Prefer this over grep/opening files."),
     "input_schema": {"type": "object", "properties": {
         "query": {"type": "string"}, "k": {"type": "integer"}, "budget": {"type": "integer"}}, "required": ["query"]}},
    {"name": "explain_symbol",
     "description": "Return the exact source of a function/class/method/table by name. Args: name (REQUIRED).",
     "input_schema": {"type": "object", "properties": {"name": {"type": "string"}}, "required": ["name"]}},
]
SHELL_TOOLS = [
    {"name": "code_search",
     "description": ("Search the repository for a regex pattern (like grep -rn). Returns matching "
                     "file:line: text. Args: pattern (REQUIRED regex string), max_results (int, default 40)."),
     "input_schema": {"type": "object", "properties": {
         "pattern": {"type": "string"}, "max_results": {"type": "integer"}}, "required": ["pattern"]}},
    {"name": "read_file",
     "description": ("Read a file, optionally a line range. Args: path (REQUIRED), start_line (int, optional), "
                     "end_line (int, optional). Prefer a narrow range over the whole file."),
     "input_schema": {"type": "object", "properties": {
         "path": {"type": "string"}, "start_line": {"type": "integer"}, "end_line": {"type": "integer"}}, "required": ["path"]}},
]

_SRC_EXT = (".luau", ".lua", ".py", ".js", ".ts", ".tsx", ".jsx", ".go", ".rs", ".java",
            ".rb", ".php", ".kt", ".c", ".cpp", ".cs", ".json", ".toml", ".md", ".txt")


def _code_search(pattern, repo, max_results=40):
    """Portable grep -rn (works on Windows too, unlike shell grep). The honest 'search'
    half of a shell agent: find where things are, then read_file a range."""
    try:
        rx = re.compile(pattern, re.I)
    except re.error as e:
        return f"(bad regex: {e})"
    hits = []
    for root, dirs, files in os.walk(repo):
        dirs[:] = [d for d in dirs if d not in (".git", ".venv", "node_modules", ".trl", "__pycache__")]
        for fn in files:
            if not fn.endswith(_SRC_EXT):
                continue
            p = os.path.join(root, fn)
            try:
                for i, line in enumerate(open(p, encoding="utf-8", errors="ignore"), 1):
                    if rx.search(line):
                        hits.append(f"{os.path.relpath(p, repo)}:{i}: {line.strip()[:200]}")
                        if len(hits) >= max_results:
                            return "\n".join(hits) + f"\n(capped at {max_results} matches)"
            except Exception:
                pass
    return "\n".join(hits) if hits else "(no matches)"


def _as_int(x, default):
    m = re.search(r"-?\d+", str(x)) if x is not None else None
    return int(m.group(0)) if m else default


def _read_file(path, repo, start=None, end=None):
    full = path if os.path.isabs(path) else os.path.join(repo, path)
    if not os.path.abspath(full).startswith(os.path.abspath(repo)):
        return "(blocked: path outside repo)"
    try:
        lines = open(full, encoding="utf-8", errors="ignore").read().splitlines()
    except Exception as e:
        return f"(read error: {e})"
    if start is not None or end is not None:
        s = max(1, _as_int(start, 1)); e = min(len(lines), _as_int(end, len(lines)))
        if e < s:
            s, e = e, s
        return f"{path}:{s}-{e}\n" + "\n".join(lines[s - 1:e])[:6000]
    return ("\n".join(lines))[:6000]


def make_executor(idx, repo):
    def execute(name, args):
        if name == "retrieve_code":
            r = trl_retrieve(idx, (args.get("query") or "").strip(),
                             token_budget=int(args.get("budget") or 1200), k=int(args.get("k") or 8))
            return r["context"] or "(no relevant symbols found)"
        if name == "explain_symbol":
            nm = (args.get("name") or "").strip()
            hits = [s for s in idx["symbols"] if s.name == nm]
            return (f"# {os.path.basename(hits[0].file)} ({nm})\n" + getattr(hits[0], "source", "")) if hits else f"(no symbol {nm})"
        if name == "code_search":
            return _code_search((args.get("pattern") or "").strip(), repo, int(args.get("max_results") or 40))
        if name == "read_file":
            return _read_file(args.get("path", ""), repo, args.get("start_line"), args.get("end_line"))
        return f"(unknown tool {name})"
    return execute


def run_session(client, model, tools, task, execute, max_turns, max_out, guard):
    messages = [{"role": "user", "content": task}]
    bi = bo = calls = tcalls = 0
    final = ""; truncated = False
    for _ in range(max_turns):
        guard.precheck(model, max_out)
        resp = client.create(model=model, max_tokens=max_out, system=SYSTEM, tools=tools, messages=messages)
        calls += 1; bi += resp.usage.input_tokens; bo += resp.usage.output_tokens
        guard.record(model, resp.usage.input_tokens, resp.usage.output_tokens)
        if resp.stop_reason == "tool_use":
            messages.append({"role": "assistant", "content": resp.raw_content})
            results = []
            for b in resp.content:
                if b.type == "tool_use":
                    tcalls += 1
                    try:
                        out = execute(b.name, b.input or {})
                    except Exception as e:
                        out = f"(tool error: {type(e).__name__}: {e})"
                    results.append({"type": "tool_result", "tool_use_id": b.id, "content": str(out)})
            messages.append({"role": "user", "content": results})
        else:
            final = " ".join(b.text for b in resp.content if b.type == "text").strip()
            break
    if not final:  # still tool-using at the cap -> force a final answer (no tools), still billed
        truncated = True
        messages.append({"role": "user", "content": "Stop using tools. Give your best final answer now from what you have."})
        guard.precheck(model, max_out)
        resp = client.create(model=model, max_tokens=max_out, system=SYSTEM, tools=None, messages=messages)
        calls += 1; bi += resp.usage.input_tokens; bo += resp.usage.output_tokens
        guard.record(model, resp.usage.input_tokens, resp.usage.output_tokens)
        final = " ".join(b.text for b in resp.content if b.type == "text").strip()
    return {"billed_in": bi, "billed_out": bo, "api_calls": calls, "tool_calls": tcalls,
            "answer": final[:800], "truncated": truncated}


def judge(client, model, task, reference, ans_mcp, ans_shell, guard):
    prompt = (f"Task: {task}\n\nReference code (ground truth):\n{reference[:4000]}\n\n"
              f"Answer A:\n{ans_mcp[:1500]}\n\nAnswer B:\n{ans_shell[:1500]}\n\n"
              "Rate each answer 0-3 for correctness and completeness vs the reference code "
              "(0=wrong/empty, 3=fully correct). A and B are anonymized; judge only on merit. "
              'Reply as strict JSON only: {"a":<0-3>,"b":<0-3>,"note":"<=12 words"}')
    try:
        guard.precheck(model, 200)
        resp = client.create(model=model, max_tokens=200, system="You are a precise, terse grader.",
                             tools=None, messages=[{"role": "user", "content": prompt}])
        guard.record(model, resp.usage.input_tokens, resp.usage.output_tokens)
        txt = " ".join(b.text for b in resp.content if b.type == "text")
        m = re.search(r"\{.*\}", txt, re.S)
        if m:
            j = json.loads(m.group(0))
            return {"mcp": int(j.get("a", 0)), "shell": int(j.get("b", 0)), "note": str(j.get("note", ""))[:80]}
        na = re.search(r'"?a"?\s*[:=]\s*(\d)', txt); nb = re.search(r'"?b"?\s*[:=]\s*(\d)', txt)
        if na and nb:
            return {"mcp": int(na.group(1)), "shell": int(nb.group(1)), "note": txt[:80]}
        return {"mcp": None, "shell": None, "note": ("unparseable: " + txt)[:80]}
    except Exception as e:
        return {"mcp": None, "shell": None, "note": f"(judge failed: {e})"[:80]}


class Guard:
    def __init__(self, cap): self.cap = cap; self.usd = 0.0
    def _c(self, m, i, o): pi, po = PRICES.get(m, (15., 75.)); return i/1e6*pi + o/1e6*po
    def precheck(self, m, mo):
        w = self._c(m, 80000, mo)
        if self.usd + w > self.cap:
            raise RuntimeError(f"HARD COST CAP hit (${self.usd:.2f} + worst ${w:.2f} > ${self.cap:.2f}). Stopping.")
    def record(self, m, i, o): self.usd += self._c(m, i, o)


class Block:
    def __init__(self, t, text=None, name=None, input=None, id=None):
        self.type, self.text, self.name, self.input, self.id = t, text, name, input, id

class Resp:
    def __init__(self, content, i, o, stop, raw):
        self.content, self.stop_reason, self.raw_content = content, stop, raw
        class U: pass
        self.usage = U(); self.usage.input_tokens = i; self.usage.output_tokens = o

class RealClient:
    def __init__(self):
        import anthropic
        self.c = anthropic.Anthropic()
    def create(self, model, max_tokens, system, messages, tools=None):
        kw = dict(model=model, max_tokens=max_tokens, system=system, messages=messages)
        if tools: kw["tools"] = tools
        m = self.c.messages.create(**kw)
        content, raw = [], []
        for b in m.content:
            if b.type == "text":
                content.append(Block("text", text=b.text)); raw.append({"type": "text", "text": b.text})
            elif b.type == "tool_use":
                content.append(Block("tool_use", name=b.name, input=b.input, id=b.id))
                raw.append({"type": "tool_use", "id": b.id, "name": b.name, "input": b.input})
        return Resp(content, m.usage.input_tokens, m.usage.output_tokens, m.stop_reason, raw)

class FakeClient:
    def __init__(self): self.turn = 0
    def create(self, model, max_tokens, system, messages, tools=None):
        approx = count_tokens(system) + sum(count_tokens(json.dumps(t)) for t in (tools or [])) + count_tokens(json.dumps(messages))
        if tools is None:  # forced answer OR judge
            if "grader" in system:
                return Resp([Block("text", text='{"a":2,"b":2,"note":"fake tie"}')], approx, 20, "end_turn", [])
            return Resp([Block("text", text="(fake) final answer.")], approx, 30, "end_turn", [])
        if self.turn < 2:
            self.turn += 1
            inp = {"query": "x"} if tools[0]["name"] == "retrieve_code" else {"cmd": "rg -n x ."}
            return Resp([Block("tool_use", name=tools[0]["name"], input=inp, id=f"t{self.turn}")], approx, 30, "tool_use",
                        [{"type": "tool_use", "id": f"t{self.turn}", "name": tools[0]["name"], "input": inp}])
        self.turn = 0
        return Resp([Block("text", text="(fake) answer.")], approx, 40, "end_turn", [{"type": "text", "text": "(fake) answer."}])


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--repo", required=True)
    ap.add_argument("--model", default=DEFAULT_MODEL)
    ap.add_argument("--max-turns", type=int, default=16)
    ap.add_argument("--max-out", type=int, default=1200)
    ap.add_argument("--usd-cap", type=float, default=4.0)
    ap.add_argument("--tasks", type=int, default=len(TASKS))
    ap.add_argument("--fake", action="store_true")
    a = ap.parse_args()

    idx = build_index(a.repo)
    print(f"repo {a.repo}: {len(idx['files'])} files, {len(idx['symbols'])} symbols | model={a.model} cap=${a.usd_cap}")
    guard = Guard(a.usd_cap)
    ex = make_executor(idx, a.repo)
    rows = []
    for i, task in enumerate(TASKS[:a.tasks], 1):
        row = {"task": task}
        try:
            for cfg, tools in (("mcp", MCP_TOOLS), ("shell", SHELL_TOOLS)):
                cli = FakeClient() if a.fake else RealClient()
                r = run_session(cli, a.model, tools, task, ex, a.max_turns, a.max_out, guard)
                row[cfg] = r
                print(f"[{i}] {cfg:5} in={r['billed_in']:6} out={r['billed_out']:4} api={r['api_calls']} "
                      f"tools={r['tool_calls']} {'TRUNC' if r['truncated'] else 'ok'}")
            ref = trl_retrieve(idx, task, token_budget=1500, k=8)["context"]
            row["judge"] = judge(FakeClient() if a.fake else RealClient(), a.model, task, ref,
                                 row["mcp"]["answer"], row["shell"]["answer"], guard)
            print(f"[{i}] judge mcp={row['judge']['mcp']} shell={row['judge']['shell']} ({row['judge']['note']})")
        except RuntimeError as e:
            print(e); rows.append(row); break
        rows.append(row)
    _summary(rows)


def _summary(rows):
    print("\n==================== PAIRED BILLED-TOKEN SUMMARY ====================")
    print(f"{'task':48}{'mcp_in':>8}{'shell_in':>9}{'delta':>8}{'qual m/s':>10}")
    tm = ts = qm = qs = qn = 0
    for r in rows:
        m, s, j = r.get("mcp"), r.get("shell"), r.get("judge") or {}
        if not m or not s: continue
        tm += m["billed_in"]; ts += s["billed_in"]
        ql = f"{j.get('mcp')}/{j.get('shell')}"
        if j.get("mcp") is not None: qm += j["mcp"]; qs += j["shell"]; qn += 1
        print(f"{r['task'][:48]:48}{m['billed_in']:>8}{s['billed_in']:>9}{m['billed_in']-s['billed_in']:>+8}{ql:>10}")
    if tm and ts:
        print("-" * 73)
        print(f"{'TOTAL billed input tokens':48}{tm:>8}{ts:>9}{tm-ts:>+8}")
        pct = 100 * (tm - ts) / ts
        print(f"MCP vs shell on BILLED INPUT: {pct:+.1f}%  -> " + ("MCP SAVED" if pct < 0 else "MCP COST MORE"))
        if qn:
            print(f"QUALITY (grader 0-3, avg over {qn}): mcp={qm/qn:.2f}  shell={qs/qn:.2f}  "
                  f"(a token result only counts if quality holds)")
    print("\n---- ANSWERS (spot-check) ----")
    for r in rows:
        if not r.get("mcp"): continue
        print("Q:", r["task"][:78])
        print("  mcp  :", (r["mcp"]["answer"] or "(empty)").replace("\n", " ")[:200])
        print("  shell:", (r["shell"]["answer"] or "(empty)").replace("\n", " ")[:200])


if __name__ == "__main__":
    main()
