from pathlib import Path

from pydantic import SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

BASE_DIR = Path(__file__).resolve().parents[3]


class Settings(BaseSettings):
    app_name: str = "Finance Dashboard API"
    app_version: str = "1.3.0"
    database_url: SecretStr | None = None
    database_path: Path = BASE_DIR / "data" / "personal_finance.db"
    frontend_path: Path = BASE_DIR / "frontend"
    cors_origins: str = "*"
    base_currency: str = "USD"

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    @field_validator("database_url", mode="before")
    @classmethod
    def validate_database_url(cls, value):
        if value is None or value == "":
            return None
        raw = value.get_secret_value() if isinstance(value, SecretStr) else value
        if not raw.startswith(("postgresql://", "postgres://")):
            raise ValueError("DATABASE_URL must be a PostgreSQL URL")
        return value

    @property
    def cors_origin_list(self) -> list[str]:
        return [origin.strip() for origin in self.cors_origins.split(",") if origin.strip()]

    @field_validator("base_currency")
    @classmethod
    def validate_base_currency(cls, value: str) -> str:
        normalized = value.strip().upper()
        if len(normalized) != 3 or not normalized.isalpha():
            raise ValueError("BASE_CURRENCY must be a three-letter ISO code")
        return normalized


settings = Settings()
