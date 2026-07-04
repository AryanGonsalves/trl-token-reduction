"""Toy suite — offline machinery validation only (mock model, no keys).

Two profiles so honesty is in the data: favorable (big prefix, verbose/redundant
tool output, mixed difficulty) and unfavorable (tiny prefix, dense novel content,
little to remove). Returns Task objects; verify=None => mock-only.
"""
import random
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
from trl.message import (Message, SYSTEM, TOOL_SCHEMA, HISTORY,
                         TOOL_RESULT, USER_QUERY)
from bench.task import Task

_PROSE = [
    "The operation proceeded through the standard pipeline stages.",
    "A retry policy was consulted and no further action was required.",
    "The subsystem reported nominal behavior across the sampled window.",
    "Downstream consumers acknowledged receipt without objection.",
    "Telemetry was flushed and the span was annotated for tracing.",
    "The scheduler considered the queue depth and left it unchanged.",
    "Verbose narration continued describing internal bookkeeping.",
    "Nothing here changes the outcome the caller actually needs.",
]


def _verbose_tool_output(rng, keyfact):
    lines = ["STATUS ok", "content-type application/json"]
    lines += [rng.choice(_PROSE) for _ in range(rng.randint(12, 18))]
    lines.append(f"KEYFACT: {keyfact}")
    lines += [rng.choice(_PROSE) for _ in range(rng.randint(12, 18))]
    return "\n".join(lines)


def _big_prefix():
    system = ("You are an autonomous coding/ops agent. " * 60)
    schemas = ("tool search query results; tool read path text; "
               "tool run cmd stdout; " * 40)
    return [Message("system", SYSTEM, system),
            Message("system", TOOL_SCHEMA, schemas)]


def make_suite(n_favorable=24, n_unfavorable=12, seed=7):
    rng = random.Random(seed)
    tasks = []
    for i in range(n_favorable):
        msgs = _big_prefix()
        hist = "\n".join([rng.choice(_PROSE) for _ in range(15)]
                         + [f"prior-decision use account {1000+i}"])
        msgs.append(Message("assistant", HISTORY, hist))
        facts = []
        for k in range(rng.randint(2, 4)):
            fact = f"order-{i}-{k} total dollars {rng.randint(10,999)}"
            facts.append(fact)
            msgs.append(Message("tool", TOOL_RESULT,
                                _verbose_tool_output(rng, fact)))
        facts.append(f"account {1000+i}")
        q = f"Reconcile order totals for batch {i}."
        msgs.append(Message("user", USER_QUERY, q))
        tasks.append(Task(f"fav-{i}", msgs, "favorable", facts, None, q))
    for i in range(n_unfavorable):
        msgs = [Message("system", SYSTEM, "You are a reasoning assistant.")]
        q = (f"Given distinct primes p={2*i+3}, q={2*i+7}, and the rule "
             f"R{i}: xor then rotate. Novel derivation required.")
        msgs.append(Message("user", USER_QUERY, q))
        tasks.append(Task(f"unf-{i}", msgs, "unfavorable",
                          [f"R{i}", f"p={2*i+3}"], None, q))
    return tasks
