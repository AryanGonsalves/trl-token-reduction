"""Task model shared by every suite (toy, realistic, tau-bench).

One shape so the harness and providers never special-case a suite:

    Task.messages      normalized request (list[Message])
    Task.profile       'favorable' | 'unfavorable'  (for honest reporting)
    Task.oracle_facts  strings the model MUST still see to answer. Used by the
                       MockModel (offline) to turn over-compression into a
                       measurable quality delta.
    Task.verify(text)  programmatic scorer for REAL model output. Returns bool.
                       None for the toy suite (mock-only).
    Task.question      the live ask appended as the user turn (real arms).
"""
from dataclasses import dataclass, field
from typing import Callable, List, Optional
from trl.message import Message


@dataclass
class Task:
    id: str
    messages: List[Message]
    profile: str
    oracle_facts: List[str] = field(default_factory=list)
    verify: Optional[Callable[[str], bool]] = None
    question: str = ""
