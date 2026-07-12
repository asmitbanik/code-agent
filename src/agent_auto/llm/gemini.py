"""Gemini client with tool calling, JSON mode, and free-tier backoff."""

from __future__ import annotations

import json
import random
import time
from typing import Any, Callable

from google import genai
from google.genai import types

from agent_auto.config import Settings


class GeminiError(RuntimeError):
    pass


class GeminiClient:
    def __init__(self, settings: Settings) -> None:
        api_key = settings.require_gemini_key()
        self.model = settings.gemini_model
        self._client = genai.Client(api_key=api_key)
        self._max_retries = 8

    def _sleep_backoff(self, attempt: int) -> None:
        base = min(60.0, (2**attempt) + random.uniform(0, 1.5))
        time.sleep(base)

    def _generate(self, **kwargs: Any) -> types.GenerateContentResponse:
        last_err: Exception | None = None
        for attempt in range(self._max_retries):
            try:
                return self._client.models.generate_content(**kwargs)
            except Exception as exc:  # noqa: BLE001 — retry boundary
                last_err = exc
                msg = str(exc).lower()
                retryable = any(
                    token in msg
                    for token in ("429", "resource_exhausted", "rate", "503", "500", "unavailable")
                )
                if not retryable or attempt == self._max_retries - 1:
                    raise GeminiError(f"Gemini request failed: {exc}") from exc
                self._sleep_backoff(attempt)
        raise GeminiError(f"Gemini request failed: {last_err}")

    def generate_text(
        self,
        *,
        system: str,
        user: str,
        temperature: float = 0.2,
    ) -> str:
        response = self._generate(
            model=self.model,
            contents=user,
            config=types.GenerateContentConfig(
                system_instruction=system,
                temperature=temperature,
            ),
        )
        text = (response.text or "").strip()
        if not text:
            raise GeminiError("Empty text response from Gemini")
        return text

    def generate_json(
        self,
        *,
        system: str,
        user: str,
        temperature: float = 0.1,
    ) -> dict[str, Any]:
        response = self._generate(
            model=self.model,
            contents=user,
            config=types.GenerateContentConfig(
                system_instruction=system,
                temperature=temperature,
                response_mime_type="application/json",
            ),
        )
        raw = (response.text or "").strip()
        if not raw:
            raise GeminiError("Empty JSON response from Gemini")
        try:
            data = json.loads(raw)
        except json.JSONDecodeError as exc:
            # One repair turn
            repaired = self.generate_text(
                system="Return only valid JSON. No markdown fences.",
                user=f"Fix this into valid JSON object:\n{raw}",
                temperature=0.0,
            )
            data = json.loads(repaired)
            if not isinstance(data, dict):
                raise GeminiError("Repaired JSON was not an object") from exc
            return data
        if not isinstance(data, dict):
            raise GeminiError("JSON response was not an object")
        return data

    def generate_with_tools(
        self,
        *,
        system: str,
        contents: list[types.Content],
        tool_declarations: list[types.FunctionDeclaration],
        temperature: float = 0.2,
    ) -> types.GenerateContentResponse:
        tools = [types.Tool(function_declarations=tool_declarations)]
        return self._generate(
            model=self.model,
            contents=contents,
            config=types.GenerateContentConfig(
                system_instruction=system,
                temperature=temperature,
                tools=tools,
                automatic_function_calling=types.AutomaticFunctionCallingConfig(
                    disable=True
                ),
            ),
        )


def extract_function_calls(response: types.GenerateContentResponse) -> list[types.FunctionCall]:
    calls: list[types.FunctionCall] = []
    if not response.candidates:
        return calls
    content = response.candidates[0].content
    if not content or not content.parts:
        return calls
    for part in content.parts:
        if part.function_call and part.function_call.name:
            calls.append(part.function_call)
    return calls


def response_text(response: types.GenerateContentResponse) -> str:
    return (response.text or "").strip()


ToolHandler = Callable[[dict[str, Any]], dict[str, Any]]
