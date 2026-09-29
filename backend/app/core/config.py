import re
from ipaddress import ip_address
from pathlib import Path
from typing import Literal
from urllib.parse import urlsplit
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import Field, SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

BASE_DIR = Path(__file__).resolve().parents[3]


class Settings(BaseSettings):
    app_name: str = "Finance Dashboard API"
    app_version: str = "1.3.0"
    database_url: SecretStr | None = None
    database_path: Path = BASE_DIR / "data" / "personal_finance.db"
    frontend_path: Path = BASE_DIR / "frontend"
    environment: Literal["development", "production"] = "development"
    cors_origins: str = "http://127.0.0.1:8000,http://localhost:8000"
    allowed_hosts: str = "localhost,127.0.0.1"
    trusted_proxy_ips: str = ""
    app_port: int = Field(default=8000, ge=1, le=65535)
    owner_username: str = Field(default="owner", min_length=1, max_length=100)
    owner_password_hash: SecretStr | None = None
    session_seconds: int = Field(default=28800, ge=60, le=86400)
    session_idle_seconds: int = Field(default=1800, ge=60, le=86400)

    @model_validator(mode="after")
    def validate_security(self):
        for origin in self.cors_origin_list:
            parts = urlsplit(origin)
            if (
                parts.scheme not in {"http", "https"}
                or not parts.hostname
                or parts.username is not None
                or parts.password is not None
                or parts.path
                or parts.query
                or parts.fragment
                or "*" in origin
            ):
                raise ValueError("CORS origins must be explicit HTTP(S) origins without paths")
            if self.environment == "production" and parts.scheme != "https":
                raise ValueError("Production origins must use HTTPS")
        if not self.cors_origin_list:
            raise ValueError("At least one explicit frontend origin is required")
        if self.environment == "production" and not self.owner_password_hash:
            raise ValueError("Production requires an owner password hash")
        if self.environment == "production":
            if len(self.cors_origin_list) != 1:
                raise ValueError("Production requires one HTTPS frontend origin")
            if urlsplit(self.cors_origin_list[0]).hostname not in self.allowed_host_list:
                raise ValueError("Production frontend hostname must be in ALLOWED_HOSTS")
            if not self.trusted_proxy_list:
                raise ValueError("Production requires explicit TRUSTED_PROXY_IPS")
        return self

    @field_validator("allowed_hosts")
    @classmethod
    def validate_allowed_hosts(cls, value: str) -> str:
        hosts = [host.strip().lower() for host in value.split(",")]
        label = r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?"
        if not hosts or any(
            not host or len(host) > 253 or re.fullmatch(label + r"(?:\." + label + r")*", host) is None
            for host in hosts
        ):
            raise ValueError("ALLOWED_HOSTS must contain exact ASCII hostnames without ports or wildcards")
        return ",".join(hosts)

    @field_validator("trusted_proxy_ips")
    @classmethod
    def validate_proxy_ips(cls, value: str) -> str:
        if not value.strip():
            return ""
        addresses = []
        for raw in value.split(","):
            try:
                address = ip_address(raw.strip())
            except ValueError as exc:
                raise ValueError(
                    "TRUSTED_PROXY_IPS must contain exact IP addresses, not wildcards or networks"
                ) from exc
            if address.is_unspecified or address.is_multicast or "%" in str(address):
                raise ValueError("TRUSTED_PROXY_IPS contains an unsuitable proxy address")
            addresses.append(str(address))
        return ",".join(addresses)

    @property
    def allowed_host_list(self) -> list[str]:
        return self.allowed_hosts.split(",")

    @property
    def trusted_proxy_list(self) -> list[str]:
        return self.trusted_proxy_ips.split(",") if self.trusted_proxy_ips else []

    @property
    def secure_cookies(self) -> bool:
        return self.environment == "production"

    business_timezone: str = "Europe/Belgrade"

    @field_validator("business_timezone")
    @classmethod
    def validate_business_timezone(cls, value: str) -> str:
        try:
            ZoneInfo(value)
        except (ZoneInfoNotFoundError, ValueError) as exc:
            raise ValueError("BUSINESS_TIMEZONE must be an installed IANA timezone name") from exc
        return value

    base_currency: str = "USD"

    model_config = SettingsConfigDict(
        env_file=".env", env_file_encoding="utf-8", extra="ignore", hide_input_in_errors=True
    )

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
