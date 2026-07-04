"""v0 product skin: an OpenAI-compatible drop-in proxy. Point your client's
base_url at this server and it applies the token-reduction levers to every
request before forwarding upstream -- zero code change for the caller."""
from .transform import transform_chat_request
__all__ = ["transform_chat_request", "transform_anthropic_request"]
