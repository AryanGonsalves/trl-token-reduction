#!/usr/bin/env python3
"""Entry point.

  python run_benchmark.py --mock                       # offline, no keys
  python run_benchmark.py --suite realistic --mock     # verifier suite, offline
  python run_benchmark.py --suite realistic --provider anthropic   # REAL ($)
  python run_benchmark.py --suite realistic --provider anthropic --dry-run
"""
import argparse, os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from trl.util import load_config
from bench.harness import run


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", default="config.yaml")
    ap.add_argument("--suite", choices=["toy", "realistic", "tau-bench"],
                    default="toy")
    ap.add_argument("--mock", action="store_true", help="force mock big-model")
    ap.add_argument("--provider", choices=["mock", "anthropic", "openai", "claude-cli"])
    ap.add_argument("--compression", choices=["safe", "aggressive"])
    ap.add_argument("--dry-run", action="store_true",
                    help="build+inspect requests without calling the API")
    ap.add_argument("--n-favorable", type=int, help="override suite.n_favorable")
    ap.add_argument("--n-unfavorable", type=int, help="override suite.n_unfavorable")
    ap.add_argument("--local-provider", choices=["mock", "ollama", "openai", "none"],
                    help="override local_model.provider (compressor)")
    ap.add_argument("--local-model", help="override local_model.model (e.g. llama3.2:3b)")
    ap.add_argument("--min-amounts", type=int, help="min records per favorable task")
    ap.add_argument("--max-amounts", type=int, help="max records per favorable task")
    args = ap.parse_args()

    cfg = load_config(args.config)
    if args.mock:
        cfg["big_model"]["provider"] = "mock"
    if args.provider:
        cfg["big_model"]["provider"] = args.provider
    if args.compression:
        cfg["arms"]["treatment"]["compression_mode"] = args.compression
    cfg.setdefault("suite", {})
    if args.n_favorable is not None:
        cfg["suite"]["n_favorable"] = args.n_favorable
    if args.n_unfavorable is not None:
        cfg["suite"]["n_unfavorable"] = args.n_unfavorable
    cfg.setdefault("local_model", {})
    if args.local_provider:
        cfg["local_model"]["provider"] = args.local_provider
    if args.local_model:
        cfg["local_model"]["model"] = args.local_model
    if args.min_amounts is not None:
        cfg["suite"]["min_amounts"] = args.min_amounts
    if args.max_amounts is not None:
        cfg["suite"]["max_amounts"] = args.max_amounts
    run(cfg, suite_name=args.suite, dry=args.dry_run)


if __name__ == "__main__":
    main()
