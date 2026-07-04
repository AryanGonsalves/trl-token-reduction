"""Realistic, self-contained, programmatically-verifiable suite.

Design goals:
  * REAL verifier, no LLM user-simulator -> runnable with ONE API key.
  * Long, redundant context (verbose JSON tool dumps + prose) so compression is
    a fair, meaningful test rather than a rigged win.
  * The answer depends on facts BURIED in the noise, so dropping them is
    punished by the verifier -> quality delta is real, not simulated.

Favorable: sum `amount_usd` across many bloated tool results. Compression must
preserve every amount or the sum is wrong.
Unfavorable: short dense arithmetic with almost nothing to remove.
"""
import random
import re
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
from trl.message import (Message, SYSTEM, TOOL_SCHEMA, HISTORY,
                         TOOL_RESULT, USER_QUERY)
from bench.task import Task

_NOISE = [
    '  "request_id": "req_%x",',
    '  "trace": "span opened; span closed",',
    '  "cache": "warm",',
    '  "note": "no action required for this record",',
    '  "region": "us-east-1",',
    '  "retries": "none",',
    '  "verbose_log": "the handler processed the record uneventfully",',
    '  "status_detail": "ok, nothing noteworthy to report here",',
]


def _make_int_verifier(expected: int):
    def verify(text: str) -> bool:
        nums = re.findall(r"-?\d+", text.replace(",", ""))
        return bool(nums) and int(nums[-1]) == expected
    return verify


def _noise_line(rng):
    t = rng.choice(_NOISE)
    return (t % rng.randrange(1 << 20)) if "%x" in t else t


def _bloated_record(rng, amount):
    """A verbose JSON-ish tool result with one load-bearing amount line."""
    lines = ["{", '  "object": "transaction",']
    lines += [_noise_line(rng) for _ in range(rng.randint(10, 16))]
    lines.append(f'  "amount_usd": {amount},')      # THE fact
    lines += [_noise_line(rng) for _ in range(rng.randint(10, 16))]
    lines.append("}")
    return "\n".join(lines)


def _stable_prefix():
    system = ("You are a financial-ops agent. Follow tool outputs exactly. "
              "Never invent numbers. " * 40)
    schemas = ("tool get_txn(id)->json; tool list()->ids; tool sum(field)->int; "
               * 30)
    return [Message("system", SYSTEM, system),
            Message("system", TOOL_SCHEMA, schemas)]


def make_realistic_suite(n_favorable=30, n_unfavorable=10, seed=7,
                         min_amounts=8, max_amounts=18):
    """Wider + higher-variance than the first cut. More transactions per task,
    each amount 2-4 digits, buried in heavier noise. Summing 8-18 numbers from a
    long noisy context is non-trivial enough that a real model occasionally errs
    even at baseline -> a REAL non-inferiority CI, not the degenerate [0,0] you
    get when every task is trivially perfect. Sizes are config-driven."""
    rng = random.Random(seed)
    tasks = []

    for i in range(n_favorable):
        msgs = _stable_prefix()
        msgs.append(Message("assistant", HISTORY,
                    "\n".join(["prior step: fetched the batch, no totals yet."] * 8)))
        amounts, facts = [], []
        for k in range(rng.randint(min_amounts, max_amounts)):
            a = rng.randint(10, 9999)
            amounts.append(a)
            facts.append(f'"amount_usd": {a}')
            msgs.append(Message("tool", TOOL_RESULT, _bloated_record(rng, a)))
        total = sum(amounts)
        q = ("Sum the amount_usd across ALL transaction tool results above. "
             "Reply with ONLY the integer total, no words.")
        msgs.append(Message("user", USER_QUERY, q))
        tasks.append(Task(f"real-fav-{i}", msgs, "favorable",
                          oracle_facts=facts,
                          verify=_make_int_verifier(total), question=q))

    for i in range(n_unfavorable):
        p, q_ = 2 * i + 51, 2 * i + 73
        msgs = [Message("system", SYSTEM, "You are a precise calculator.")]
        prompt = (f"Let a={p}, b={q_}. Compute (a*b) mod 1000. "
                  f"Reply with ONLY the integer.")
        msgs.append(Message("user", USER_QUERY, prompt))
        tasks.append(Task(f"real-unf-{i}", msgs, "unfavorable",
                          oracle_facts=[str(p), str(q_)],
                          verify=_make_int_verifier((p * q_) % 1000),
                          question=prompt))
    return tasks
