"""Application configuration, loaded from environment / .env."""
from __future__ import annotations

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    secret_key: str = "dev-insecure-secret-change-me"

    # Storage
    database_url: str = "sqlite:///./data/garage.db"
    receipts_dir: str = "./data/receipts"

    # Claude Vision (receipt OCR)
    anthropic_api_key: str = ""
    vision_model: str = "claude-opus-4-8"

    # Email
    smtp_host: str = ""
    smtp_port: int = 587
    smtp_user: str = ""
    smtp_password: str = ""
    smtp_use_tls: bool = True
    alert_email_from: str = "garage@example.com"
    alert_email_to: str = ""
    # Public base URL of the app, used for the "open the app" button in the
    # digest email. Empty = no button rendered.
    app_url: str = ""

    # Initial users, "name:email:password" comma-separated
    initial_users: str = ""

    @property
    def vision_enabled(self) -> bool:
        return bool(self.anthropic_api_key)

    @property
    def email_enabled(self) -> bool:
        return bool(self.smtp_host)


@lru_cache
def get_settings() -> Settings:
    return Settings()
