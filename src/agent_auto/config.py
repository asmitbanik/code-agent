"""Runtime configuration from environment."""

from __future__ import annotations

from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # LLM provider: groq (default) | gemini
    llm_provider: str = Field(default="groq", alias="LLM_PROVIDER")

    groq_api_key: str = Field(default="", alias="GROQ_API_KEY")
    groq_model: str = Field(
        default="llama-3.1-8b-instant",
        alias="GROQ_MODEL",
    )

    gemini_api_key: str = Field(default="", alias="GEMINI_API_KEY")
    gemini_model: str = Field(default="gemini-2.5-flash", alias="GEMINI_MODEL")

    gh_token: str = Field(default="", alias="GH_TOKEN")
    github_token: str = Field(default="", alias="GITHUB_TOKEN")
    agent_max_iterations: int = Field(default=20, alias="AGENT_MAX_ITERATIONS")
    agent_max_subtasks: int = Field(default=6, alias="AGENT_MAX_SUBTASKS")
    agent_workdir: Path = Field(default=Path("./runs"), alias="AGENT_WORKDIR")
    shell_timeout_sec: int = Field(default=300, alias="AGENT_SHELL_TIMEOUT")
    max_tool_output_chars: int = Field(default=8_000, alias="AGENT_MAX_TOOL_OUTPUT")
    agent_skip_browser: bool = Field(default=False, alias="AGENT_SKIP_BROWSER")
    agent_skip_planner: bool = Field(default=True, alias="AGENT_SKIP_PLANNER")

    @property
    def github_auth_token(self) -> str:
        return self.gh_token or self.github_token

    def require_llm_key(self) -> str:
        provider = self.llm_provider.strip().lower()
        if provider == "groq":
            if not self.groq_api_key.strip():
                raise ValueError("GROQ_API_KEY is not set. Export it or add it to .env.")
            return self.groq_api_key.strip()
        if not self.gemini_api_key.strip():
            raise ValueError("GEMINI_API_KEY is not set. Export it or add it to .env.")
        return self.gemini_api_key.strip()


def get_settings() -> Settings:
    return Settings()
