"""Index persistence + incremental rebuild. Run: python tests/test_index_persistence.py"""
import sys, os, tempfile
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from trl.retrieval import build_index, save_index, load_index

def test_incremental_and_roundtrip():
    d = tempfile.mkdtemp()
    for i in range(3):
        open(os.path.join(d, f"m{i}.py"), "w").write(f"def f{i}():\n    return {i}\n")
    idx = build_index(d)
    p = os.path.join(d, "index.json"); save_index(idx, p)
    loaded = load_index(p)
    assert {s.name for s in loaded["symbols"]} == {s.name for s in idx["symbols"]}
    open(os.path.join(d, "m1.py"), "w").write("def f1():\n    return 999\n")
    idx2 = build_index(d, prev=loaded)
    st = idx2["_stats"]
    assert [os.path.basename(x) for x in st["reparsed"]] == ["m1.py"]
    assert st["reused"] == 2
    assert any(s.name == "f1" and "999" in s.source for s in idx2["symbols"])
    print("persistence+incremental OK: reparsed only changed file, reused rest")

if __name__ == "__main__":
    test_incremental_and_roundtrip()
    print("INDEX PERSISTENCE TEST PASSED")


def test_load_index_has_stats_parity():
    # FIX: load_index used to drop _stats; callers reading index["_stats"] after a
    # round-trip would KeyError. Now it is present (all symbols "reused").
    import tempfile, os as _os
    from trl.retrieval.ast_index import build_index, save_index, load_index
    d = tempfile.mkdtemp()
    open(_os.path.join(d, "m.py"), "w").write("def f():\n    return g()\n")
    sp = _os.path.join(d, "idx.json")
    save_index(build_index(d), sp)
    li = load_index(sp)
    assert "_stats" in li and li["_stats"]["reused"] == len(li["symbols"])
