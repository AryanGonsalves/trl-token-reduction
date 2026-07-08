"""Compression of the growing tail: history + raw tool outputs.

Governing principle (do not violate): remove what the model doesn't need; never
compress what it does. 'safe' mode only removes provable redundancy. 'aggressive'
mode summarizes harder and is EXPECTED to occasionally drop something needed —
the benchmark exists to catch exactly that as a quality delta.

Perf: we compress the ENTIRE compressible tail in ONE local-model call per
request (not one call per message). With a slow local model this is ~Nx fewer
calls and the difference between a run finishing in a minute vs hanging.
"""
import hashlib
import re
from collections import OrderedDict

from .message import Message, COMPRESSIBLE_KINDS
from .local_model import heuristic_compress

_NUM = re.compile(r"-?\d[\d,]*")

_INSTR = ("Compress the following tool outputs and conversation history for "
          "re-use as context.")


# O2: memoize per-message compression. In an agent loop the settled tail is
# byte-identical step to step, so only the NEW message actually hits the (slow/
# paid) local model -- the rest are served from cache. Output is identical to
# recomputing; this is pure memoization, quality-neutral.
_COMPRESS_CACHE: "OrderedDict[tuple, str]" = OrderedDict()
_CACHE_MAX = 512


def _clear_compress_cache():
    _COMPRESS_CACHE.clear()


def _compress_one(content: str, mode: str, local_model) -> str:
    """Compress ONE message's content, memoized by (content, mode, provider,
    model). The fact guard runs per message in safe mode; aggressive stays lossy."""
    key = (hashlib.sha256(content.encode("utf-8")).hexdigest(), mode,
           getattr(local_model, "provider", ""), getattr(local_model, "model", ""))
    cached = _COMPRESS_CACHE.get(key)
    if cached is not None:
        _COMPRESS_CACHE.move_to_end(key)
        return cached
    if mode == "aggressive":
        out = _aggressive(content)
    else:
        out = local_model.summarize(content, _INSTR)
        out = _preserve_facts(content, out)   # exact fact safety net, per message
    _COMPRESS_CACHE[key] = out
    if len(_COMPRESS_CACHE) > _CACHE_MAX:
        _COMPRESS_CACHE.popitem(last=False)
    return out


def compress_request(messages, mode, local_model, kinds=COMPRESSIBLE_KINDS):
    """Return (new_messages, stats). Collapses the whole compressible tail into a
    single compressed message via ONE local-model call. `kinds` selects WHICH
    message kinds are eligible (defaults to all COMPRESSIBLE_KINDS); the engine
    narrows it so the compress_history / compress_tool_outputs flags act
    independently."""
    compressible = [m for m in messages
                    if m.kind in kinds and len(m.content) > 200]
    if not compressible:
        return messages, {"messages_compressed": 0}

    combined = "\n\n".join(m.content for m in compressible)
    # Compress each message independently (memoized) then join. Folding N messages
    # into one call was the old perf design; per-message memoization is faster in a
    # loop (only new messages recompute) while producing an equivalent blob.
    new_blob = "\n\n".join(_compress_one(m.content, mode, local_model)
                            for m in compressible)
    # Guard: never expand, never blank.
    if not new_blob.strip() or len(new_blob) >= len(combined):
        new_blob = heuristic_compress(combined)
        # FACT-GUARD INVARIANT: heuristic_compress has NO fact guard (it strips
        # boilerplate-prefixed lines, which can carry numbers). In safe mode the
        # guard MUST cover this fallback too, or a verbose real-model compressor
        # that trips the never-expand branch could silently drop a load-bearing
        # number. Aggressive mode stays intentionally lossy.
        if mode != "aggressive":
            new_blob = _preserve_facts(combined, new_blob)
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
    # Preserve key_facts from every folded message (dedup, order-stable). It's
    # eval-only metadata today, but blanking it silently loses information the
    # folded blob is meant to carry.
    folded_facts, _seen = [], set()
    for m in compressible:
        for f in m.key_facts:
            if f not in _seen:
                _seen.add(f); folded_facts.append(f)
    for m in messages:
        if m.kind in kinds and len(m.content) > 200:
            if not inserted:
                out.append(Message(keep.role, keep.kind, new_blob, folded_facts))
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
