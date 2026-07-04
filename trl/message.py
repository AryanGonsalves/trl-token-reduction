"""Normalized request model.

A request is an ordered list of Messages. `kind` is what lets the engine act
semantically instead of blindly — it's the thing a pure wire proxy can't see
without heuristics, and the reason the SDK/plugin skin can do more than the
proxy skin.
"""
from dataclasses import dataclass, field
from typing import List

# kinds, roughly in prefix->tail order
SYSTEM = "system"            # system prompt (stable)
TOOL_SCHEMA = "tool_schema"  # tool/function definitions (stable)
HISTORY = "history"          # prior conversation turns (grows every step)
TOOL_RESULT = "tool_result"  # raw tool output (often huge, often redundant)
USER_QUERY = "user_query"    # the live ask (never touch this)

STABLE_KINDS = {SYSTEM, TOOL_SCHEMA}
COMPRESSIBLE_KINDS = {HISTORY, TOOL_RESULT}


@dataclass
class Message:
    role: str          # system|user|assistant|tool
    kind: str
    content: str
    # key_facts: information the big model MUST retain to succeed. Used by the
    # mock quality model to detect over-compression; in real runs it's unused
    # metadata but handy for building eval tasks with known answers.
    key_facts: List[str] = field(default_factory=list)

    def copy_with(self, content: str) -> "Message":
        return Message(self.role, self.kind, content, list(self.key_facts))
