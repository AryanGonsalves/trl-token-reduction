"""Run both arms over a suite, meter everything, judge against the gates."""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
from trl import Engine, count_tokens
from trl.message import COMPRESSIBLE_KINDS
from trl.cache import stable_prefix
from bench.providers import get_provider
from bench import accounting as acct
from bench.stats import noninferiority


def _local_tokens(messages):
    return sum(count_tokens(m.content) for m in messages
               if m.kind in COMPRESSIBLE_KINDS)


def load_suite(name, config):
    seed = config.get("seed", 7)
    sz = config.get("suite", {}) or {}
    if name == "toy":
        from bench.tasks import make_suite
        return make_suite(seed=seed)
    if name == "realistic":
        from bench.realistic_tasks import make_realistic_suite
        return make_realistic_suite(
            n_favorable=sz.get("n_favorable", 30),
            n_unfavorable=sz.get("n_unfavorable", 10), seed=seed,
            min_amounts=sz.get("min_amounts", 8),
            max_amounts=sz.get("max_amounts", 18))
    if name == "tau-bench":
        from bench.tau_bench_adapter import load_tau_bench
        return load_tau_bench()
    raise ValueError(f"unknown suite: {name}")


def run(config, suite_name="toy", dry=False):
    model = get_provider(config["big_model"]["provider"], config)
    engine = Engine(config)
    price, sub = config["big_model"], config["subscription_model"]
    local_cfg = config["local_model"]
    native = config["arms"]["baseline"]["native_prompt_cache"]
    suite = load_suite(suite_name, config)

    import sys as _sys, time as _time, os as _os
    _pace = float(_os.environ.get("PACE_SECONDS", "0") or 0)
    rows = []
    for _i, task in enumerate(suite):
        print(f"[{_i+1}/{len(suite)}] {task.id} ({task.profile})",
              file=_sys.stderr, flush=True)
        msgs = task.messages
        b_prefix = stable_prefix(msgs)[1]
        b = model.call(msgs, task, b_prefix, native, dry)

        if _pace:
            _time.sleep(_pace)
        res = engine.process(msgs)
        t = model.call(res.messages, task, res.cache_prefix_tokens, native, dry)
        if _pace:
            _time.sleep(_pace)

        rows.append({
            "profile": task.profile,
            "b_cost": acct.api_cost(b.usage, price),
            "t_cost": acct.api_cost(t.usage, price) + acct.local_cost(
                _local_tokens(msgs), local_cfg),
            "b_units": acct.subscription_units(b.usage, sub),
            "t_units": acct.subscription_units(t.usage, sub),
            "b_in": b.usage["input_tokens"], "t_in": t.usage["input_tokens"],
            "b_ok": int(b.success), "t_ok": int(t.success),
        })
    return _report(rows, config, suite_name, dry)


def _agg(rows, key):
    return sum(r[key] for r in rows)


def _report(rows, config, suite_name, dry):
    margin = config["gates"]["quality_noninferiority_margin"]
    min_mult = config["gates"]["min_savings_multiple_favorable"]
    L = ["=" * 68,
         " TOKEN-REDUCTION BENCHMARK  (suite=%s, mode=%s, provider=%s%s)"
         % (suite_name, config["arms"]["treatment"]["compression_mode"],
            config["big_model"]["provider"], ", DRY" if dry else ""),
         "=" * 68]

    results = {}
    for profile in ("favorable", "unfavorable", "ALL"):
        rs = rows if profile == "ALL" else [r for r in rows if r["profile"] == profile]
        if not rs:
            continue
        b_cost, t_cost = _agg(rs, "b_cost"), _agg(rs, "t_cost")
        b_in, t_in = _agg(rs, "b_in"), _agg(rs, "t_in")
        b_u, t_u = _agg(rs, "b_units"), _agg(rs, "t_units")
        mult = (b_cost / t_cost) if t_cost else float("inf")
        tok_red = 100 * (1 - t_in / b_in) if b_in else 0
        unit_red = 100 * (1 - t_u / b_u) if b_u else 0
        results[profile] = {"mult": mult, "tok_red": tok_red}
        L += ["", f" [{profile}]  n={len(rs)}",
              f"   API $:        {b_cost:.5f} -> {t_cost:.5f}   ({mult:.2f}x, net of local)",
              f"   input tokens: {b_in:,} -> {t_in:,}   ({tok_red:.1f}% less)",
              f"   sub. units:   {b_u:,.0f} -> {t_u:,.0f}   ({unit_red:.1f}% less)"]

    ni = noninferiority([r["b_ok"] for r in rows], [r["t_ok"] for r in rows],
                        margin, seed=config.get("seed", 7))
    L += ["", " QUALITY (non-inferiority test, paired)",
          f"   baseline success:  {ni['baseline_success']*100:.1f}%",
          f"   treatment success: {ni['treatment_success']*100:.1f}%",
          f"   delta: {ni['delta']*100:+.1f} pts   95% CI "
          f"[{ni['ci95'][0]*100:+.1f}, {ni['ci95'][1]*100:+.1f}]   "
          f"margin {ni['margin']*100:.1f} pts",
          f"   non-inferior: {'PASS' if ni['non_inferior'] else 'FAIL'}"]

    fav_mult = results.get("favorable", {}).get("mult", 0)
    savings_ok = fav_mult >= min_mult
    if dry:
        verdict = "DRY RUN (no quality signal; request/token structure only)"
    else:
        verdict = ("SHIP-WORTHY so far" if (ni["non_inferior"] and savings_ok)
                   else "DOES NOT CLEAR GATE")
    L += ["", " GATES (pre-registered)",
          f"   favorable savings {fav_mult:.2f}x  vs required {min_mult:.1f}x  "
          f"-> {'PASS' if savings_ok else 'FAIL'}",
          f"   quality non-inferior            -> {'PASS' if ni['non_inferior'] else 'FAIL'}",
          "=" * 68, f" VERDICT: {verdict}", "=" * 68]
    report = "\n".join(L)
    print(report)
    return {"results": results, "noninferiority": ni,
            "gate_pass": bool(ni["non_inferior"] and savings_ok and not dry),
            "report": report}
