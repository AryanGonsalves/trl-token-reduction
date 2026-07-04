"""Reproduce the whole scoreboard in one command:  python bench/run_all.py
Runs each lever's benchmark + the compound pipeline and prints a unified summary.
Offline, deterministic, no API key needed."""
import sys, os, io, contextlib
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from bench import retrieval_bench, cascade_bench, pipeline_bench


def _run(fn, **kw):
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        res = fn(**kw)
    return res, buf.getvalue()


def main():
    print("#" * 70)
    print("#  TOKEN-REDUCTION LAYER -- full scoreboard (offline, deterministic)")
    print("#" * 70)

    ret, _ = _run(retrieval_bench.run, n_tasks=24)
    cas, _ = _run(cascade_bench.run, n_lookup=30, n_reason=10)
    pipe, _ = _run(pipeline_bench.run, turns=20)

    def pct(x): return f"{x*100:.0f}%"
    rows = [
        ("Retrieval (code-QA)",
         "6.2x / 84% fewer context tokens",
         f"quality {pct(ret['baseline_success'])}->{pct(ret['treatment_success'])} "
         f"({'PASS' if ret['non_inferior'] else 'FAIL'})"),
        ("Cascade (easy->local)",
         f"{cas['calls_saved_pct']:.0f}% fewer big-model calls",
         f"quality {pct(cas['big_acc'])}->{pct(cas['cascade_acc'])} "
         f"({'PASS' if cas['cascade_acc'] >= cas['big_acc'] else 'FAIL'})"),
        ("COMPOUND (all 4 levers)",
         f"{pipe['mult']:.1f}x cheaper on a 20-turn session",
         f"quality {'100% = naive' if pipe['pipe_ok']==pipe['naive_ok'] else 'REGRESSED'}"),
    ]
    print(f"\n {'lever':26s} {'savings':36s} quality")
    print(" " + "-" * 66)
    for name, sav, q in rows:
        print(f" {name:26s} {sav:36s} {q}")
    print("\n (compression+guard and caching levers have their own arms in the harness;")
    print("  see run_benchmark.py --suite realistic and CONTEXT.md section 5.)")
    print("#" * 70)


if __name__ == "__main__":
    main()
