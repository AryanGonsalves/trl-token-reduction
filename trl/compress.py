"""Compression of the growing tail: history + raw tool outputs.

Governing principle (do not violate): remove what the model doesn't need; never
compress what it does. 'safe' mode only removes provable redundancy. 'aggressive'
mode summarizes harder and is EXPECTED to occasionally drop something needed —
the benchmark exists to catch exactly that as a quality delta.

Perf: we compress the ENTIRE compressible tail in ONE local-model call per
request (not one call per message). With a slow local model this is ~Nx fewer
calls and the difference between a run finishing in a minute vs hanging.
"""
import re

from .message import Message, COMPRESSIBLE_KINDS
from .local_model import heuristic_compress

_NUM = re.compile(r"-?\d[\d,]*")

_INSTR = ("Compress the following tool outputs and conversation history for "
          "re-use as context.")


def compress_request(messages, mode, local_model):
    """Return (new_messages, stats). Collapses the whole compressible tail into a
    single compressed message via ONE local-model call."""
    compressible = [m for m in messages
                    if m.kind in COMPRESSIBLE_KINDS and len(m.content) > 200]
    if not compressible:
        return messages, {"messages_compressed": 0}

    combined = "\n\n".join(m.content for m in compressible)
    if mode == "aggressive":
        new_blob = _aggressive(combined)
    else:
        new_blob = local_model.summarize(combined, _INSTR)
        new_blob = _preserve_facts(combined, new_blob)   # exact fact safety net
    # Guard: never expand.
    if not new_blob or len(new_blob) >= len(combined):
        new_blob = heuristic_compress(combined)
        # If the heuristic can't shrink it, OR would blank the message entirely
        # (e.g. the whole tail is boilerplate), decline to compress and keep the
        # original messages. Never fold a run of messages into empty content --
        # LocalModel.summarize's contract is "never blank out".
        if not new_blob.strip() or len(new_blob) >= len(combined):
            return messages, {"messages_compressed": 0}

    # Replace the run of compressible messages with one compressed message,
    # in place (keeps stable prefix and the live user query where they were).
    out, inserted = [], False
    keep = compressible[0]
    for m in messages:
        if m.kind in COMPRESSIBLE_KINDS and len(m.content) > 200:
            if not inserted:
                out.append(Message(keep.role, keep.kind, new_blob, []))
                inserted = True
            # drop the other compressible messages (folded into the blob)
        else:
            out.append(m)
    return out, {"messages_compressed": len(compressible)}


def _preserve_facts(original: str, compressed: str) -> str:
    """Deterministic safety net over a lossy LLM compressor: guarantee every
    numeric fact (amounts, ids, counts) in `original` survives. For any number
    missing from `compressed`, re-inject the exact source line that carries it.
    Cheap, exact, and turns a fact-dropping compressor into a quality-safe one --
    at the cost of a few re-added lines (only what was actually lost)."""
    comp_nums = set(_NUM.findall(compressed.replace(",", "")))
    reinjected, seen = [], set()
    for line in original.splitlines():
        nums = _NUM.findall(line.replace(",", ""))
        if any(n not in comp_nums for n in nums):
            key = line.strip()
            if key and key not in seen and key not in compressed:
                seen.add(key)
                reinjected.append(key)
    if not reinjected:
        return compressed
    tail = "\n".join(reinjected)
    # Avoid a leading blank line when the compressed side was empty.
    return compressed + "\n" + tail if compressed else tail


def _aggressive(text: str) -> str:
    """Lossy summarization stand-in. Keeps the head and a deduped skeleton but
    will drop detail buried in the tail — realistic failure mode for an
    over-eager summarizer. Kept deterministic for reproducibility."""
    deduped = heuristic_compress(text).splitlines()
    if len(deduped) <= 3:
        return "\n".join(deduped)
    head = deduped[:2]
    return "\n".join(head + [f"[summarized {len(deduped) - 2} more lines]"])
