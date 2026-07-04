"""Big-model providers. Uniform Response so the harness is provider-agnostic
(covers 'GPT and Claude').

Uniform usage dict (the honest number depends on it):
    input_tokens         TOTAL prompt tokens (full-rate + cached)
    cached_input_tokens  prompt tokens served from native cache (cheap rate)
    output_tokens        completion tokens
accounting.py bills (input-cached) at full and cached at the cache-read rate.
"""
from dataclasses import dataclass
from typing import Dict, List
import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
from trl.message import Message, STABLE_KINDS, USER_QUERY
from trl.util import count_tokens


@dataclass
class Response:
    text: str
    usage: Dict[str, int]
    success: bool


def get_provider(name, cfg):
    return {"mock": MockModel, "anthropic": AnthropicModel,
            "openai": OpenAIModel, "claude-cli": ClaudeCLIModel}[name](cfg)


def split_request(messages: List[Message]):
    """-> (stable_prefix_text, tail_text, question). The stable prefix is what
    gets cache-marked; the tail is the compressed history+tool output; the
    question is the live user turn (never compressed)."""
    stable, tail, question = [], [], ""
    for m in messages:
        if m.kind in STABLE_KINDS:
            stable.append(m.content)
        elif m.kind == USER_QUERY:
            question = m.content
        else:
            tail.append(m.content)
    return "\n".join(stable), "\n".join(tail), question


# --------------------------------------------------------------------------
class MockModel:
    """Offline stand-in. success = every oracle fact still present in the
    context actually received. This is what makes over-compression measurable."""
    def __init__(self, cfg):
        self.cfg = cfg

    def call(self, messages, task, cache_prefix_tokens, native_cache, dry=False):
        import re
        blob = "\n".join(m.content for m in messages)

        def survived(fact):
            # Check the NUMERIC values in the fact survived compression. Robust
            # to a real LLM compressor that paraphrases (e.g. '"amount_usd": 300'
            # -> 'amount 300' / '$300') -- we only care that 300 is still there.
            nums = re.findall(r"\d+", fact)
            return all(n in blob for n in nums) if nums else (fact in blob)

        success = all(survived(f) for f in task.oracle_facts)
        in_tok = sum(count_tokens(m.content) for m in messages)
        cached = cache_prefix_tokens if native_cache else 0
        return Response("[mock]", {"input_tokens": in_tok,
                                   "cached_input_tokens": cached,
                                   "output_tokens": 180}, success)


# --------------------------------------------------------------------------
class AnthropicModel:
    def __init__(self, cfg):
        self.cfg = cfg
        self.model = cfg["big_model"]["anthropic_model"]
        # auth: auto (prefer subscription token, else API key) | subscription | api_key
        self.auth_mode = cfg["big_model"].get("anthropic_auth", "auto")
        self._client = None

    def _client_lazy(self):
        if self._client is None:
            import anthropic
            from bench.subscription_auth import get_oauth_token
            tok = get_oauth_token() if self.auth_mode in ("auto", "subscription") else None
            if self.auth_mode == "subscription" and not tok:
                raise RuntimeError(
                    "anthropic_auth=subscription but no OAuth token found. Run "
                    "`claude setup-token` and set CLAUDE_CODE_OAUTH_TOKEN (or log in "
                    "via VoiceClaw).")
            if tok:
                # Subscription: Bearer token, no API key (the voiceclaw way).
                self._client = anthropic.Anthropic(auth_token=tok, max_retries=8)
            else:
                self._client = anthropic.Anthropic(max_retries=8)  # metered API key from env
        return self._client

    def _build(self, messages, native_cache):
        stable, tail, question = split_request(messages)
        system = [{"type": "text", "text": stable}]
        if native_cache:
            system[0]["cache_control"] = {"type": "ephemeral"}
        user = (tail + "\n\n" + question) if tail else question
        return system, [{"role": "user", "content": user}]

    def call(self, messages, task, cache_prefix_tokens, native_cache, dry=False):
        system, msgs = self._build(messages, native_cache)
        if dry:
            est = count_tokens(system[0]["text"]) + count_tokens(msgs[0]["content"])
            return Response("[dry]", {"input_tokens": est,
                                      "cached_input_tokens": cache_prefix_tokens
                                      if native_cache else 0,
                                      "output_tokens": 0}, False)
        r = self._client_lazy().messages.create(
            model=self.model, max_tokens=64, system=system, messages=msgs)
        text = "".join(b.text for b in r.content if b.type == "text")
        u = r.usage
        cache_read = getattr(u, "cache_read_input_tokens", 0) or 0
        cache_create = getattr(u, "cache_creation_input_tokens", 0) or 0
        total_in = u.input_tokens + cache_read + cache_create
        usage = {"input_tokens": total_in, "cached_input_tokens": cache_read,
                 "output_tokens": u.output_tokens}
        return Response(text, usage, bool(task.verify and task.verify(text)))


# --------------------------------------------------------------------------
class OpenAIModel:
    def __init__(self, cfg):
        self.cfg = cfg
        self.model = cfg["big_model"]["openai_model"]
        self._client = None

    def _client_lazy(self):
        if self._client is None:
            import openai
            self._client = openai.OpenAI(timeout=30, max_retries=3)  # reads OPENAI_API_KEY
        return self._client

    def _build(self, messages):
        stable, tail, question = split_request(messages)
        user = (tail + "\n\n" + question) if tail else question
        return [{"role": "system", "content": stable},
                {"role": "user", "content": user}]

    def call(self, messages, task, cache_prefix_tokens, native_cache, dry=False):
        msgs = self._build(messages)
        if dry:
            est = sum(count_tokens(m["content"]) for m in msgs)
            return Response("[dry]", {"input_tokens": est,
                                      "cached_input_tokens": cache_prefix_tokens
                                      if native_cache else 0,
                                      "output_tokens": 0}, False)
        # OpenAI auto-caches >1024-token prefixes; nothing to set. Read cached.
        r = self._client_lazy().chat.completions.create(
            model=self.model, max_tokens=64, messages=msgs)
        text = r.choices[0].message.content or ""
        u = r.usage
        cached = 0
        if getattr(u, "prompt_tokens_details", None):
            cached = getattr(u.prompt_tokens_details, "cached_tokens", 0) or 0
        usage = {"input_tokens": u.prompt_tokens, "cached_input_tokens": cached,
                 "output_tokens": u.completion_tokens}
        return Response(text, usage, bool(task.verify and task.verify(text)))


# --------------------------------------------------------------------------
class ClaudeCLIModel:
    """Run the big-model calls through the LOCAL Claude Code CLI on the user's
    SUBSCRIPTION (no metered API key). This measures the World-B meter that
    matters for the coding-agent wedge: subscription usage consumption.

    Honest caveats (see CONTEXT/RUN):
      * We do NOT use --bare: bare mode needs an API key and skips subscription
        OAuth. Normal `-p` uses your subscription login.
      * To keep measurement clean we REPLACE Claude Code's default system prompt
        with our stable prefix (--system-prompt) and run from a clean temp cwd so
        no CLAUDE.md / .mcp.json is auto-loaded. Residual CC scaffold overhead
        hits both arms equally -> relative savings valid, absolute inflated.
      * Native prefix caching is CC-managed and opaque; cached_input_tokens comes
        from whatever CC reports. Treat sub-usage numbers as directional.

    First run: `--dry-run` prints the exact command. Then run one real call and
    eyeball the JSON; usage field names are parsed defensively below.
    """
    def __init__(self, cfg):
        self.cfg = cfg
        c = cfg.get("claude_cli", {})
        self.bin = c.get("bin", "claude")
        self.model = c.get("model", "")          # "" -> subscription default
        self.extra = c.get("extra_args", [])
        self.timeout = c.get("timeout_s", 120)
        self.use_subscription = c.get("use_subscription", True)

    def _cmd(self):
        base = [self.bin, "-p", "--output-format", "json",
                "--permission-mode", "bypassPermissions"]
        if self.model:
            base += ["--model", self.model]
        base += list(self.extra)
        # Windows: `claude` is a .cmd shim; subprocess can't exec it directly.
        # Route through the shell so PATHEXT resolves claude.cmd.
        if os.name == "nt":
            return [os.environ.get("COMSPEC", "cmd.exe"), "/c"] + base
        return base

    def call(self, messages, task, cache_prefix_tokens, native_cache, dry=False):
        import subprocess, tempfile
        stable, tail, question = split_request(messages)
        # Pipe the WHOLE thing via stdin (no giant --system-prompt arg -> no
        # cmd quoting hell). CC prepends its own default system prompt; that
        # overhead is equal across arms, so relative savings stay valid.
        parts = [x for x in (stable, tail, question) if x]
        stdin_text = "\n\n".join(parts)
        cmd = self._cmd()
        if dry:
            est = count_tokens(stdin_text)
            return Response("[dry] " + " ".join(cmd) ,
                            {"input_tokens": est, "cached_input_tokens": 0,
                             "output_tokens": 0}, False)
        # Force SUBSCRIPTION OAuth: strip any API-key env vars so the CLI does
        # not try (stale) API-key auth and 401. This is the whole point -- we
        # want to measure subscription usage, not a metered key.
        env = dict(os.environ)
        # Prefer Claude Code's OWN stored login. Only if a REAL oauth token is
        # available do we inject it (and then hide a stale API key so it wins).
        from bench.subscription_auth import get_oauth_token
        tok = get_oauth_token()
        if tok:
            env["CLAUDE_CODE_OAUTH_TOKEN"] = tok
            for k in ("ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN"):
                env.pop(k, None)
        with tempfile.TemporaryDirectory() as cwd:   # clean dir: no CLAUDE.md
            proc = subprocess.run(cmd, input=stdin_text, capture_output=True,
                                  text=True, cwd=cwd, timeout=self.timeout, env=env)
        if proc.returncode != 0:
            raise RuntimeError(f"claude CLI failed ({proc.returncode}): "
                               f"{(proc.stderr or proc.stdout)[:400]}")
        return parse_claude_cli_json(proc.stdout, task)


def parse_claude_cli_json(stdout: str, task) -> "Response":
    """Parse `claude -p --output-format json`. Isolated + defensive so it can be
    unit-tested offline and tolerate minor schema drift."""
    import json as _json
    data = _json.loads(stdout)
    text = data.get("result", "") or ""
    u = data.get("usage", {}) or {}
    inp = u.get("input_tokens", 0) or 0
    cache_read = u.get("cache_read_input_tokens", 0) or 0
    cache_create = u.get("cache_creation_input_tokens", 0) or 0
    out = u.get("output_tokens", 0) or 0
    usage = {"input_tokens": inp + cache_read + cache_create,
             "cached_input_tokens": cache_read,
             "output_tokens": out,
             # CC's own dollar estimate (subscription-equivalent), for reference
             "cli_cost_usd": data.get("total_cost_usd", 0.0)}
    return Response(text, usage, bool(task.verify and task.verify(text)))
