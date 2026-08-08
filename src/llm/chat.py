"""Factory for building the configured LLM client, kept separate from
app.py so Streamlit reruns don't need to know the provider-specific
construction details."""
from __future__ import annotations

from typing import Optional

from .anthropic_client import AnthropicClient
from .base import LLMClient, LLMError
from .openai_compatible import OpenAICompatibleClient

__all__ = ["LLMClient", "LLMError", "build_client"]


def build_client(
    provider: str,
    *,
    api_key: str = "",
    model: str = "",
    base_url: str = "",
) -> Optional[LLMClient]:
    """provider: 'claude' or 'local'. Returns None if required fields are missing
    (the caller should treat that as "not configured yet", not an error)."""
    if provider == "claude":
        if not api_key or not model:
            return None
        return AnthropicClient(api_key=api_key, model=model)
    if provider == "local":
        if not base_url or not model:
            return None
        return OpenAICompatibleClient(base_url=base_url, model=model, api_key=api_key)
    return None
