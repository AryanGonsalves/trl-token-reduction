"""Core of the proxy: turn a caller's OpenAI chat request into a leaner one.

Maps the request's messages onto the engine's semantic kinds, then applies the
engine (cache-mark stable prefix + compress the growing tail with the fact
guard). The system prefix and the LIVE user turn are never touched; prior turns
and tool outputs are compressed. Pure + deterministic -> unit-testable with no
network."""
from __future__ import annotations

from typing import Dict, List, Tuple

from trl import Engine
from trl.message import (Message, SYSTEM, TOOL_SCHEMA, HISTORY, TOOL_RESULT,
                         USER_QUERY)
from trl.util import count_tokens


def _kind_for(role: str, is_last_user: bool) -> str:
    if role == "system":
        return SYSTEM
    if role in ("tool", "function"):
        return TOOL_RESULT
    if role == "user":
        return USER_QUERY if is_last_user else HISTORY
    return HISTORY   # assistant / other prior turns -> compressible history


def _apply_document_retrieval(req: Dict, budget: int = 1500) -> Dict:
    """If the request carries a non-standard `documents` field (a list of strings
    or {name,text}), replace it with ONLY the passages relevant to the live user
    query -- so callers can hand us whole docs/PDF-text and we retrieve instead of
    stuffing. Removes `documents` before forwarding (it's not a real API param)."""
    docs = req.get("documents")
    if not docs:
        return req
    from trl.retrieval import build_text_index, retrieve_text
    messages = list(req.get("messages", []))
    query = next((m.get("content", "") for m in reversed(messages)
                  if m.get("role") == "user" and isinstance(m.get("content"), str)), "")
    docmap = {}
    for i, d in enumerate(docs):
        if isinstance(d, str):
            docmap[f"doc{i}"] = d
        elif isinstance(d, dict):
            docmap[d.get("name", f"doc{i}")] = d.get("text", "") or d.get("content", "")
    idx = build_text_index(docmap)
    r = retrieve_text(idx, query or "", token_budget=budget, k=8)
    insert_at = 0
    while insert_at < len(messages) and messages[insert_at].get("role") == "system":
        insert_at += 1
    if r["context"]:
        messages.insert(insert_at, {"role": "system",
                                    "content": "Relevant context (retrieved):\n" + r["context"]})
    out = {k: v for k, v in req.items() if k != "documents"}
    out["messages"] = messages
    return out


def transform_chat_request(req: Dict, engine: Engine) -> Tuple[Dict, Dict]:
    """(new_request, meta). Applies document-retrieval (if `documents` present),
    then cache-marking + tail compression. Multimodal / tool-call messages pass
    through untouched."""
    req = _apply_document_retrieval(req)
    messages: List[Dict] = req.get("messages", [])

    # Requests carrying tool-call plumbing or multimodal content have strict
    # ordering/field requirements (a `tool` message must directly follow its
    # assistant `tool_calls` message and keep its `tool_call_id`). Folding or
    # reordering them would produce an invalid upstream request, so we pass
    # those through unchanged rather than risk correctness for savings.
    if any(not isinstance(m.get("content"), str) or m.get("tool_calls")
           or m.get("tool_call_id") for m in messages if isinstance(m, dict)):
        before = sum(count_tokens(m.get("content"))
                     for m in messages
                     if isinstance(m, dict) and isinstance(m.get("content"), str))
        meta = {"tokens_before": before, "tokens_after": before,
                "tokens_saved": 0, "cache_prefix_tokens": 0,
                "engine": {"bypass": "complex_messages"}}
        return req, meta

    last_user = max((i for i, m in enumerate(messages)
                     if m.get("role") == "user"), default=-1)

    trl_msgs, passthrough = [], {}
    for i, m in enumerate(messages):
        content = m.get("content")
        if not isinstance(content, str) or m.get("tool_calls"):
            passthrough[i] = m               # leave complex messages alone
            trl_msgs.append(Message(m.get("role", "user"), USER_QUERY, ""))
            continue
        trl_msgs.append(Message(m.get("role", "user"),
                                _kind_for(m.get("role", "user"), i == last_user),
                                content))

    before = sum(count_tokens(m.get("content", "") if isinstance(m.get("content"), str) else "")
                 for m in messages)
    res = engine.process(trl_msgs)

    # rebuild -- compression may have folded several tail messages into one, so
    # we map processed messages back, preserving passthroughs by position where
    # they still exist.
    new_messages = []
    for m in res.messages:
        role = m.role if m.role in ("system", "user", "assistant", "tool") else "user"
        new_messages.append({"role": role, "content": m.content})
    # re-insert untouched complex messages that were passthrough
    # (simplest safe behavior: if any passthrough existed, keep originals for them)
    if passthrough:
        kept = [messages[i] for i in sorted(passthrough)]
        new_messages = kept + [nm for nm in new_messages if nm["content"]]

    after = sum(count_tokens(nm.get("content", "")) for nm in new_messages)
    new_req = {**req, "messages": new_messages}
    meta = {"tokens_before": before, "tokens_after": after,
            "tokens_saved": max(before - after, 0),
            "cache_prefix_tokens": res.cache_prefix_tokens,
            "engine": res.meta}
    return new_req, meta


# --------------------------------------------------------------------------
# Anthropic Messages API shape (system param + messages + cache_control blocks)
def _to_text(content):
    """Anthropic content can be a string or a list of blocks; return plain text
    if it's simple text, else None (leave complex/multimodal content alone)."""
    if isinstance(content, str):
        return content
    if isinstance(content, list) and all(
            isinstance(b, dict) and b.get("type") == "text" for b in content):
        return "\n".join(b.get("text", "") for b in content)
    return None


def transform_anthropic_request(req: Dict, engine: Engine) -> Tuple[Dict, Dict]:
    """Compress prior turns + inject cache_control on the stable system prefix
    (the caching lever, explicit for Anthropic). The live (last user) turn and any
    complex/multimodal content are left untouched."""
    messages = req.get("messages", [])
    system = req.get("system", "")
    sys_text = _to_text(system) if system else ""

    # Multimodal / tool-use blocks have ordering requirements a fold-and-rebuild
    # can't honor (a tool_result must follow its tool_use turn). If any message
    # carries complex content, skip compression entirely and only apply the
    # (order-preserving) cache_control lever on the system prefix.
    if any(_to_text(m.get("content")) is None
           for m in messages if isinstance(m, dict)):
        before = count_tokens(sys_text or "") + sum(
            count_tokens(_to_text(m.get("content")) or "") for m in messages)
        new_req = dict(req)
        if sys_text:
            new_req["system"] = [{"type": "text", "text": sys_text,
                                  "cache_control": {"type": "ephemeral"}}]
        meta = {"tokens_before": before, "tokens_after": before,
                "tokens_saved": 0,
                "cache_prefix_tokens": count_tokens(sys_text or "")}
        return new_req, meta

    last_user = max((i for i, m in enumerate(messages)
                     if m.get("role") == "user"), default=-1)

    trl_msgs = [Message("system", SYSTEM, sys_text or "")]
    idx_map = []                       # position of each transformable message
    for i, m in enumerate(messages):
        text = _to_text(m.get("content"))
        if text is None:
            continue                   # skip complex content in the engine pass
        kind = USER_QUERY if (m.get("role") == "user" and i == last_user) else HISTORY
        trl_msgs.append(Message(m.get("role", "user"), kind, text))
        idx_map.append(i)

    before = count_tokens(sys_text) + sum(
        count_tokens(_to_text(m.get("content")) or "") for m in messages)
    res = engine.process(trl_msgs)

    # res.messages[0] is the (unchanged) system; rest map back to messages order,
    # with the history possibly folded into fewer messages.
    new_system_text = res.messages[0].content if res.messages else sys_text
    tail = [m for m in res.messages[1:]]
    new_messages = []
    # rebuild messages: keep complex ones in place, replace text ones with tail
    complex_msgs = [m for i, m in enumerate(messages) if _to_text(m.get("content")) is None]
    for m in complex_msgs:
        new_messages.append(m)
    for m in tail:
        if m.content:
            new_messages.append({"role": m.role if m.role in ("user", "assistant") else "user",
                                 "content": m.content})

    # inject cache_control on the stable system prefix (caching lever)
    new_system = [{"type": "text", "text": new_system_text,
                   "cache_control": {"type": "ephemeral"}}] if new_system_text else system

    after = count_tokens(new_system_text) + sum(count_tokens(nm.get("content", ""))
                                                for nm in new_messages
                                                if isinstance(nm.get("content"), str))
    new_req = {**req, "system": new_system, "messages": new_messages}
    meta = {"tokens_before": before, "tokens_after": after,
            "tokens_saved": max(before - after, 0),
            "cache_prefix_tokens": res.cache_prefix_tokens}
    return new_req, meta
