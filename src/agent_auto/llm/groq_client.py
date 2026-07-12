"""Groq OpenAI-compatible client (primary LLM)."""

from __future__ import annotations

import json
import random
import time
from typing import Any

import httpx

from agent_auto.config import Settings


class LLMError(RuntimeError):
    pass


class GroqClient:
    def __init__(self, settings: Settings) -> None:
        key = settings.groq_api_key.strip()
        if not key:
            raise ValueError("GROQ_API_KEY is not set.")
        self.model = settings.groq_model
        self._api_key = key
        self._base = "https://api.groq.com/openai/v1"
        self._max_retries = 6

    def _sleep_backoff(self, attempt: int) -> None:
        time.sleep(min(45.0, (2**attempt) + random.uniform(0, 1.0)))

    def _post(self, payload: dict[str, Any]) -> dict[str, Any]:
        last_err: Exception | None = None
        for attempt in range(self._max_retries):
            try:
                with httpx.Client(timeout=120.0) as client:
                    resp = client.post(
                        f"{self._base}/chat/completions",
                        headers={
                            "Authorization": f"Bearer {self._api_key}",
                            "Content-Type": "application/json",
                        },
                        json=payload,
                    )
                if resp.status_code in {429, 500, 502, 503}:
                    last_err = LLMError(f"Groq HTTP {resp.status_code}: {resp.text[:300]}")
                    if attempt == self._max_retries - 1:
                        raise last_err
                    self._sleep_backoff(attempt)
                    continue
                if resp.status_code >= 400:
                    raise LLMError(f"Groq HTTP {resp.status_code}: {resp.text[:500]}")
                return resp.json()
            except LLMError:
                raise
            except Exception as exc:  # noqa: BLE001
                last_err = exc
                if attempt == self._max_retries - 1:
                    raise LLMError(f"Groq request failed: {exc}") from exc
                self._sleep_backoff(attempt)
        raise LLMError(f"Groq request failed: {last_err}")

    def generate_text(
        self,
        *,
        system: str,
        user: str,
        temperature: float = 0.2,
        max_tokens: int = 4096,
    ) -> str:
        data = self._post(
            {
                "model": self.model,
                "temperature": temperature,
                "max_tokens": max_tokens,
                "messages": [
                    {"role": "system", "content": system},
                    {"role": "user", "content": user},
                ],
            }
        )
        try:
            text = data["choices"][0]["message"]["content"] or ""
        except (KeyError, IndexError, TypeError) as exc:
            raise LLMError(f"Unexpected Groq response: {data!r}") from exc
        text = text.strip()
        if not text:
            raise LLMError("Empty text response from Groq")
        return text

    def generate_json(
        self,
        *,
        system: str,
        user: str,
        temperature: float = 0.1,
        max_tokens: int = 2048,
    ) -> dict[str, Any]:
        raw = self.generate_text(
            system=system + "\nRespond with a single JSON object only. No markdown.",
            user=user,
            temperature=temperature,
            max_tokens=max_tokens,
        )
        raw = raw.strip()
        if raw.startswith("```"):
            raw = raw.strip("`")
            if raw.startswith("json"):
                raw = raw[4:]
            raw = raw.strip()
        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            repaired = self.generate_text(
                system="Return only valid JSON object. No markdown.",
                user=f"Fix into JSON object:\n{raw[:4000]}",
                temperature=0.0,
                max_tokens=max_tokens,
            )
            data = json.loads(repaired)
        if not isinstance(data, dict):
            raise LLMError("JSON response was not an object")
        return data

    def chat_with_tools(
        self,
        *,
        system: str,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]],
        temperature: float = 0.2,
        max_tokens: int = 2048,
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "model": self.model,
            "temperature": temperature,
            "max_tokens": max_tokens,
            "messages": [{"role": "system", "content": system}, *messages],
        }
        if tools:
            payload["tools"] = tools
            payload["tool_choice"] = "auto"
        data = self._post(payload)
        try:
            msg = data["choices"][0]["message"]
        except (KeyError, IndexError, TypeError) as exc:
            raise LLMError(f"Unexpected Groq tool response: {data!r}") from exc
        return msg
