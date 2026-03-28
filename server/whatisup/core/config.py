"""Application configuration via environment variables."""

from __future__ import annotations

import logging

from pydantic import Field, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

logger = logging.getLogger(__name__)

_DEFAULT_SECRET = "CHANGE_ME_IN_PRODUCTION"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # Application
    app_name: str = "WhatIsUp"
    app_version: str = "0.12.1"
    debug: bool = False
    environment: str = "production"

    # Security
    secret_key: str = _DEFAULT_SECRET
    jwt_algorithm: str = "HS256"
    # Fernet key for encrypting alert channel secrets at rest
    # Generate: python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"  # noqa: E501
    fernet_key: str = ""
    access_token_expire_minutes: int = 15
    refresh_token_expire_days: int = 7

    # CORS
    cors_allowed_origins: list[str] = Field(default=["http://localhost:5173"])

    @field_validator("cors_allowed_origins", mode="before")
    @classmethod
    def parse_cors(cls, v: str | list[str]) -> list[str]:
        if isinstance(v, str):
            return [origin.strip() for origin in v.split(",") if origin.strip()]
        return v

    # Database
    database_url: str = "postgresql+asyncpg://whatisup:whatisup@localhost:5432/whatisup"

    # Redis
    redis_url: str = "redis://localhost:6379/0"

    # Email (SMTP)
    smtp_host: str = "localhost"
    smtp_port: int = 587
    smtp_user: str = ""
    smtp_password: str = ""
    smtp_from: str = "noreply@example.com"
    smtp_tls: bool = True

    # Probe
    probe_result_rate_limit: str = "30/minute"
    probe_heartbeat_interval_seconds: int = 30

    # Data retention
    data_retention_days: int = 90  # 0 = keep forever

    # OIDC / SSO
    oidc_enabled: bool = False
    oidc_issuer_url: str = ""        # e.g. https://accounts.google.com
    oidc_client_id: str = ""
    oidc_client_secret: str = ""
    oidc_redirect_uri: str = ""      # full callback URL; auto-derived if empty
    oidc_scopes: str = "openid email profile"
    # If True, create a new local account on first OIDC login (invite-only = False)
    oidc_auto_provision: bool = True

    # Web Push (VAPID)
    # Generate keys:
    #   python -c "from py_vapid import Vapid; v=Vapid(); v.generate_keys();
    #              print('Private:', v.private_key); print('Public:', v.public_key_urlsafe)"
    vapid_private_key: str = ""   # PEM string or base64url private key
    vapid_public_key: str = ""    # base64url public key — sent to frontend
    vapid_contact_email: str = "admin@example.com"

    # Feature flags
    registration_open: bool = True  # False = invite-only after first user

    @model_validator(mode="after")
    def validate_production_settings(self) -> Settings:
        if self.environment == "production":
            if self.secret_key == _DEFAULT_SECRET:
                raise ValueError(
                    "SECRET_KEY is set to the default value — "
                    "refusing to start in production. Set the SECRET_KEY env var."
                )
            # Enforce HTTPS-only CORS origins in production
            http_origins = [o for o in self.cors_allowed_origins if o.startswith("http://")]
            if http_origins:
                raise ValueError(
                    f"CORS_ALLOWED_ORIGINS contains insecure HTTP origins in production: "
                    f"{http_origins}. Use HTTPS."
                )
            if not self.fernet_key:
                raise ValueError(
                    "FERNET_KEY is not set — scenario variable secrets and alert channel "
                    "credentials would be stored in plaintext. "
                    "Generate one with: python -c \"from cryptography.fernet import Fernet; "
                    "print(Fernet.generate_key().decode())\""
                )
        return self

    @property
    def is_production(self) -> bool:
        return self.environment == "production"


_settings: Settings | None = None


def get_settings() -> Settings:
    global _settings
    if _settings is None:
        _settings = Settings()
    return _settings
