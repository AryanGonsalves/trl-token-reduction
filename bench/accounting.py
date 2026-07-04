"""Turn raw usage into the three meters we care about: API dollars,
subscription usage units, and net-of-preprocessor-cost savings."""


def api_cost(usage, price):
    """$ for one call. Cached prefix billed at the cheap cache-read rate."""
    full_in = usage["input_tokens"] - usage.get("cached_input_tokens", 0)
    cached = usage.get("cached_input_tokens", 0)
    out = usage["output_tokens"]
    return (full_in * price["price_in_per_mtok"]
            + cached * price["price_cached_in_per_mtok"]
            + out * price["price_out_per_mtok"]) / 1_000_000


def subscription_units(usage, sub):
    """Claude-Code / Cursor style budget. Cached input costs a token fraction."""
    full_in = usage["input_tokens"] - usage.get("cached_input_tokens", 0)
    cached = usage.get("cached_input_tokens", 0)
    out = usage["output_tokens"]
    return (full_in * sub["input_weight"]
            + cached * sub["input_weight"] * 0.1
            + out * sub["output_weight"])


def local_cost(tokens_processed, local_cfg):
    """Notional cost of running the preprocessor. Counted AGAINST savings so the
    headline is net, not gross (the preprocessor is not free)."""
    return tokens_processed * local_cfg.get("notional_cost_per_mtok", 0.0) / 1_000_000
