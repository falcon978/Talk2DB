"""Factory for the ChatOllama LLM client."""

from langchain_ollama import ChatOllama
from agri_sql_agent.config import settings


def get_llm() -> ChatOllama:
    """Instantiates and returns the configured ChatOllama client."""
    return ChatOllama(
        model=settings.llm_model_name,
        base_url=settings.ollama_base_url,
        temperature=settings.llm_temperature
    )
