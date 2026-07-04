"""Engine — the shared core behind BOTH skins (Claude Code plugin + API proxy).

Contract is deliberately one method:

    result = Engine(config).process(messages)

`result.messages`      -> the (possibly compressed) request to send onward
`result.cache_prefix_tokens` -> tokens the provider should cache-mark
`result.meta`          -> what we did, for accounting + debugging

The engine NEVER touches the live user query and never invents information. It
only (a) marks the stable prefix for caching and (b) removes redundancy from the
growing tail via the local preprocessor.
"""
from dataclasses import dataclass, field
from typing import List, Dict

from .message import Message
from .local_model import LocalModel
from .cache import stable_prefix
from .compress import compress_request
from .util import count_tokens


@dataclass
class Result:
    messages: List[Message]
    cache_prefix_tokens: int
    meta: Dict = field(default_factory=dict)


class Engine:
    def __init__(self, config: dict):
        self.cfg = config = config or {}   # tolerate empty/None config
        arm = (config.get("arms") or {}).get("treatment") or {}
        self.use_cache = arm.get("native_prompt_cache", True)
        self.compress_history = arm.get("compress_history", True)
        self.compress_tool_outputs = arm.get("compress_tool_outputs", True)
        self.mode = arm.get("compression_mode", "safe")
        self.local = LocalModel(config.get("local_model", {}))

    def process(self, messages: List[Message]) -> Result:
        meta = {"mode": self.mode, "local_model_used": self.local.available()}

        # 1) identify cacheable stable prefix
        prefix_tokens = 0
        if self.use_cache:
            _, prefix_tokens = stable_prefix(messages)

        # 2) compress the tail
        out = messages
        if self.compress_history or self.compress_tool_outputs:
            out, cstats = compress_request(messages, self.mode, self.local)
            meta.update(cstats)

        before = sum(count_tokens(m.content) for m in messages)
        after = sum(count_tokens(m.content) for m in out)
        meta["tokens_before"] = before
        meta["tokens_after"] = after
        meta["tokens_removed"] = before - after
        return Result(out, prefix_tokens, meta)
