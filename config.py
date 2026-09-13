"""
Configuration for the presentation layer (UI and API).
"""

from pydantic_settings import BaseSettings, SettingsConfigDict

class AppConfig(BaseSettings):
    """Centralized configuration for the Streamlit UI and FastAPI endpoints."""
    
    api_url: str = "http://localhost:8000"
    ui_page_title: str = "Talk2DB"
    api_title: str = "Talk2DB API"

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore"
    )

config = AppConfig()
