"""Optional Gemini adapter (same interface as Groq)."""

from __future__ import annotations

import json
from typing import Any

from google import genai
from google.genai import types

from agent_auto.config import Settings
from agent_auto.llm.groq_client import LLMError


class GeminiAdapter:
    def __init__(self, settings: Settings) -> None:
        key = settings.gemini_api_key.strip()
        if not key:
            raise ValueError("GEMINI_API_KEY is not set.")
        self.model = settings.gemini_model
        self._client = genai.Client(api_key=key)

    def generate_text(
        self,
        *,
        system: str,
        user: str,
        temperature: float = 0.2,
        max_tokens: int = 4096,
    ) -> str:
        response = self._client.models.generate_content(
            model=self.model,
            contents=user,
            config=types.GenerateContentConfig(
                system_instruction=system,
                temperature=temperature,
                max_output_tokens=max_tokens,
            ),
        )
        text = (response.text or "").strip()
        if not text:
            raise LLMError("Empty text response from Gemini")
        return text

    def generate_json(
        self,
        *,
        system: str,
        user: str,
        temperature: float = 0.1,
        max_tokens: int = 2048,
    ) -> dict[str, Any]:
        response = self._client.models.generate_content(
            model=self.model,
            contents=user,
            config=types.GenerateContentConfig(
                system_instruction=system,
                temperature=temperature,
                max_output_tokens=max_tokens,
                response_mime_type="application/json",
            ),
        )
        raw = (response.text or "").strip()
        data = json.loads(raw)
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
        # Convert OpenAI-style tools to Gemini function declarations
        decls = []
        for tool in tools:
            fn = tool.get("function") or {}
            params = fn.get("parameters") or {"type": "object", "properties": {}}
            decls.append(
                types.FunctionDeclaration(
                    name=fn.get("name"),
                    description=fn.get("description"),
                    parameters=params,
                )
            )
        contents: list[types.Content] = []
        for msg in messages:
            role = msg.get("role")
            if role == "tool":
                contents.append(
                    types.Content(
                        role="user",
                        parts=[
                            types.Part(
                                function_response=types.FunctionResponse(
                                    name=msg.get("name") or "tool",
                                    response={"result": msg.get("content")},
                                )
                            )
                        ],
                    )
                )
            elif role == "assistant" and msg.get("tool_calls"):
                parts = []
                for tc in msg["tool_calls"]:
                    fn = tc.get("function") or {}
                    args = fn.get("arguments") or "{}"
                    if isinstance(args, str):
                        try:
                            args = json.loads(args)
                        except json.JSONDecodeError:
                            args = {}
                    parts.append(
                        types.Part(
                            function_call=types.FunctionCall(
                                name=fn.get("name"),
                                args=args,
                            )
                        )
                    )
                contents.append(types.Content(role="model", parts=parts))
            else:
                gem_role = "user" if role == "user" else "model"
                contents.append(
                    types.Content(
                        role=gem_role,
                        parts=[types.Part(text=str(msg.get("content") or ""))],
                    )
                )

        response = self._client.models.generate_content(
            model=self.model,
            contents=contents,
            config=types.GenerateContentConfig(
                system_instruction=system,
                temperature=temperature,
                max_output_tokens=max_tokens,
                tools=[types.Tool(function_declarations=decls)],
                automatic_function_calling=types.AutomaticFunctionCallingConfig(
                    disable=True
                ),
            ),
        )
        tool_calls = []
        text_bits: list[str] = []
        if response.candidates and response.candidates[0].content:
            for part in response.candidates[0].content.parts or []:
                if part.function_call and part.function_call.name:
                    tool_calls.append(
                        {
                            "id": f"call_{part.function_call.name}",
                            "type": "function",
                            "function": {
                                "name": part.function_call.name,
                                "arguments": json.dumps(dict(part.function_call.args or {})),
                            },
                        }
                    )
                elif part.text:
                    text_bits.append(part.text)
        out: dict[str, Any] = {"role": "assistant", "content": "\n".join(text_bits).strip() or None}
        if tool_calls:
            out["tool_calls"] = tool_calls
        return out
