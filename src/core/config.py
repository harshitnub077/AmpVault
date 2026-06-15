from functools import lru_cache
from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    PROJECT_NAME: str = "Escrowatt"
    VERSION: str = "0.1.0"
    ENVIRONMENT: Literal["development", "test", "production"] = "development"
    DEBUG: bool = False

    # Database & Cache
    DATABASE_URL: str = "sqlite+aiosqlite:///escrowatt.db"
    REDIS_URL: str = "redis://localhost:6379/0"

    # Security & Auth
    JWT_SECRET: str = "escrowatt-insecure-dev-secret-key-32-bytes-minimum"
    JWT_ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 60
    REFRESH_TOKEN_EXPIRE_DAYS: int = 7

    # Webhook Secrets
    GATEWAY_WEBHOOK_SECRET: str = "whsec_mock_gateway_secret_key_12345"
    COURIER_WEBHOOK_SECRET: str = "whsec_mock_courier_secret_key_67890"

    # Business Constraints
    DEFAULT_CURRENCY: str = "INR"
    PLATFORM_ESCROW_FEE_BPS: int = 150  # 1.5% platform fee (150 basis points)
    INSPECTION_WINDOW_HOURS: int = 72

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )


@lru_cache
def get_settings() -> Settings:
    return Settings()
