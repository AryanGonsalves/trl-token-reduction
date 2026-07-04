"""trl — the shared token-reduction engine.

Public surface intentionally tiny so both skins (Claude Code plugin, API proxy)
depend on the same thing:

    from trl import Engine, Message, count_tokens
"""
from .message import Message
from .util import count_tokens, load_config
from .engine import Engine

__all__ = ["Engine", "Message", "count_tokens", "load_config"]
