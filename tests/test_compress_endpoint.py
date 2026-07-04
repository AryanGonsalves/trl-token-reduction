"""Offline tests for the /compress endpoint (composer extension backend)."""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from proxy.compress_endpoint import handle_compress
from trl.local_model import LocalModel


class FakeEngine:
    mode = "safe"
    local = LocalModel({"provider": "none"})   # offline -> heuristic compressor


def test_compress_preserves_numbers_and_shrinks():
    text = ("Order 4471 confirmed. Order 4471 confirmed. Total is 300 dollars.\n" * 8 +
            "Shipping to zone 5. Shipping to zone 5. Invoice id 99812.\n" * 8)
    r = handle_compress({"text": text, "mode": "compress"}, FakeEngine())
    assert r["tokens_after"] < r["tokens_before"]
    for n in ("4471", "300", "5", "99812"):
        assert n in r["compressed"], f"lost {n}"
        assert n in r["preserved_facts"]
    print("compress OK:", r["tokens_before"], "->", r["tokens_after"])


def test_retrieve_mode_selects_relevant_passage():
    doc = ("Section A: the cache lever bills the stable prefix once.\n\n"
           "Section B: the compression lever summarizes the growing tail.\n\n"
           "Section C: the cascade lever routes easy steps to a local model.\n")
    r = handle_compress({"text": doc, "question": "how does cascade route steps?",
                         "mode": "retrieve"}, FakeEngine())
    assert "cascade" in r["compressed"].lower()
    print("retrieve OK")


def test_empty_text_errors():
    r = handle_compress({"text": "   "}, FakeEngine())
    assert "error" in r
    print("empty OK")


if __name__ == "__main__":
    test_compress_preserves_numbers_and_shrinks()
    test_retrieve_mode_selects_relevant_passage()
    test_empty_text_errors()
    print("ALL COMPRESS-ENDPOINT TESTS PASSED")
