"""tau-bench adapter — the external, credible agentic benchmark.

Why it's a separate module: tau-bench needs its own install and API keys (it
uses an LLM to simulate the user), so we keep it optional. The realistic suite
(bench/realistic_tasks.py) is the zero-friction path; tau-bench is the
publish-grade path.

INSTALL:
    git clone https://github.com/sierra-research/tau-bench
    pip install -e ./tau-bench
    export ANTHROPIC_API_KEY=... (or OPENAI_API_KEY)

MAP (fill in _to_task): tau-bench exposes environments (retail, airline) whose
episodes give: a system/policy prompt, a tool schema, an evolving message
history, and a programmatic reward at the end. Convert each into a Task:
  * SYSTEM     <- policy prompt
  * TOOL_SCHEMA<- tool defs
  * HISTORY    <- prior turns
  * TOOL_RESULT<- each tool observation (this is the compressible bloat)
  * USER_QUERY <- the current user turn
  * verify     <- wrap tau-bench's reward check (reward==1 -> True)
  * oracle_facts <- optional: the slots/ids the episode's reward depends on,
                    so the offline MockModel stays meaningful too.

Keeping the SAME Task shape means accounting + stats + gates are untouched:
only the task source changes.
"""


def load_tau_bench(env="retail", split="test", limit=50):
    raise NotImplementedError(
        "Install tau-bench (see module docstring), then implement _to_task() to "
        "map episodes onto bench.task.Task. The rest of the harness is ready.")
