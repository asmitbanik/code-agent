"""Shared LLM protocol and factory."""

from __future__ import annotations

from typing import Any, Protocol

from agent_auto.config import Settings


class LLMClient(Protocol):
    model: str

    def generate_text(
        self,
        *,
        system: str,
        user: str,
        temperature: float = 0.2,
        max_tokens: int = 4096,
    ) -> str: ...

    def generate_json(
        self,
        *,
        system: str,
        user: str,
        temperature: float = 0.1,
        max_tokens: int = 2048,
    ) -> dict[str, Any]: ...

    def chat_with_tools(
        self,
        *,
        system: str,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]],
        temperature: float = 0.2,
        max_tokens: int = 2048,
    ) -> dict[str, Any]: ...


def create_llm(settings: Settings) -> LLMClient:
    provider = settings.llm_provider.strip().lower()
    if provider == "gemini":
        from agent_auto.llm.gemini_adapter import GeminiAdapter

        return GeminiAdapter(settings)
    from agent_auto.llm.groq_client import GroqClient

    return GroqClient(settings)
