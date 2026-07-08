"""Summarize the TRL retrieval-savings log written by the plugin.

Set TRL_SAVINGS_LOG when you launch Claude Code, build, then run:
  python -m validate.savings_report [path]
Reports adoption (how often the tools were actually called) + tokens saved vs
whole-file reads, cumulative across every session that appended to the log."""
import sys, json, os

def main():
    path = sys.argv[1] if len(sys.argv) > 1 else os.environ.get("TRL_SAVINGS_LOG", ".trl/savings.jsonl")
    if not os.path.exists(path):
        print("no savings log at", path, "-- set TRL_SAVINGS_LOG and use the plugin first."); return
    recs = [json.loads(l) for l in open(path, encoding="utf-8") if l.strip()]
    if not recs:
        print("empty log at", path); return
    rc = sum(1 for r in recs if r["tool"] == "retrieve_code")
    es = sum(1 for r in recs if r["tool"] == "explain_symbol")
    slice_t = sum(r["slice_tokens"] for r in recs)
    whole_t = sum(r["wholefile_tokens"] for r in recs)
    saved = sum(r["saved"] for r in recs)
    print(f"TRL retrieval savings  ({path})")
    print(f"  ADOPTION: {len(recs)} tool calls  ({rc} retrieve_code, {es} explain_symbol)")
    print(f"  slice tokens actually sent:   {slice_t:,}")
    print(f"  whole-file counterfactual:    {whole_t:,}")
    if whole_t:
        print(f"  TOKENS SAVED vs whole-file reads: {saved:,}  ({100*saved/whole_t:.1f}% fewer)")
    print(f"  (adoption is the key number: if the agent rarely calls these, real savings are small)")

if __name__ == "__main__":
    main()
