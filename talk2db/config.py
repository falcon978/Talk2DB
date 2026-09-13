"""
Loads and validates environment variables and application configurations.
"""

import os
from typing import Optional
from pydantic_settings import BaseSettings, SettingsConfigDict

class Settings(BaseSettings):
    """Centralized, type-safe configuration loaded from environment variables or .env file."""

    # LLM Configuration
    ollama_base_url: str
    llm_model_name: str
    llm_temperature: float = 0.0

    # Database & Cache Configuration
    redis_url: str
    db_dsn_app: str
    db_dsn_target: str
    
    # Core Agent Logic
    max_retries: int = 2
    db_timeout_seconds: float = 3.0
    cache_ttl_seconds: int = 3600
    context_window_turns: int = 3
    result_row_limit: int = 100
    wildcard_min_length: int = 3

    # LangSmith Observability
    langchain_tracing_v2: str = "false"
    langchain_project: str
    langchain_api_key: Optional[str] = None

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore"
    )

settings = Settings()

# Force inject telemetry vars into os.environ for LangChain's internal hooks.
# Only enable tracing if a valid API key is provided to prevent errors for evaluators.
if settings.langchain_tracing_v2.lower() == "true" and settings.langchain_api_key:
    os.environ["LANGCHAIN_TRACING_V2"] = "true"
    os.environ["LANGCHAIN_API_KEY"] = settings.langchain_api_key
    if settings.langchain_project:
        os.environ["LANGCHAIN_PROJECT"] = settings.langchain_project
else:
    # Disable tracing if no API key is available or tracing is explicitly off
    os.environ["LANGCHAIN_TRACING_V2"] = "false"

