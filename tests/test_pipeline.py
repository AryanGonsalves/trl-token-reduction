"""Compound pipeline: levers stack, quality preserved. Run: python tests/test_pipeline.py"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from bench.pipeline_bench import run

def test_compound():
    r = run(turns=20)
    assert r["pipe_ok"] == r["naive_ok"], "pipeline lost quality vs naive"
    assert r["mult"] > 3.0, f"compound saving too low: {r['mult']:.1f}x"
    print(f"pipeline OK: {r['mult']:.1f}x cheaper, quality-neutral")

if __name__ == "__main__":
    test_compound()
    print("PIPELINE TEST PASSED")
