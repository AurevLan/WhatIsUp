"""Application configuration via environment variables."""

from __future__ import annotations

import logging
from importlib.metadata import PackageNotFoundError
from importlib.metadata import version as _pkg_version

from pydantic import Field, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

logger = logging.getLogger(__name__)

_DEFAULT_SECRET = "CHANGE_ME_IN_PRODUCTION"


def _default_app_version() -> str:
    """Real release version from package metadata (release-please bumps it)."""
    try:
        return _pkg_version("whatisup-server")
    except PackageNotFoundError:  # editable/dev checkout without install
        return "0.0.0-dev"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # Application
    app_name: str = "WhatIsUp"
    app_version: str = _default_app_version()
    debug: bool = False
    environment: str = "production"
    # V2 Global Health Engine — emergency rollback. When True, the per-probe
    # legacy decider runs even on monitors with health_engine_enabled=True.
    # Flip to True (no code change, no migration) if M5 misbehaves in prod.
    legacy_incident_engine: bool = False

    # Security
    secret_key: str = _DEFAULT_SECRET
    jwt_algorithm: str = "HS256"
    # Fernet key for encrypting alert channel secrets at rest
    # Generate: python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"  # noqa: E501
    fernet_key: str = ""
    # Previous Fernet key(s) — comma-separated, accepted for DECRYPTION only
    # during a key rotation. Encryption always uses FERNET_KEY (primary).
    # Procedure: SECURITY.md §7 "Rotation FERNET_KEY (zéro downtime)" +
    # `python -m whatisup.tools.rotate_fernet`.
    fernet_key_previous: str = ""
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

    # Reverse-proxy trust boundary (audit F4/F13/F14).
    # Comma-separated IPs / CIDRs whose X-Forwarded-For and X-Forwarded-Proto
    # headers are believed. Everything else is treated as a client that may be
    # forging them: the real peer wins. The default covers loopback and the
    # RFC1918 / ULA ranges docker networks live in, so the shipped
    # docker-compose stack works out of the box while a directly-reachable API
    # cannot be told "I am 9.9.9.9" by whoever connects to it.
    # ``*`` restores the old always-trust behaviour and is refused in production.
    trusted_proxy_ips: str = "127.0.0.1,::1,10.0.0.0/8,172.16.0.0/12,192.168.0.0/16,fc00::/7"

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

    # Racine publique utilisée pour construire les liens des e-mails
    # (confirmation et désinscription des pages de statut). Le serveur ne peut
    # pas la deviner : il est derrière un reverse proxy et ne voit ni le nom
    # d'hôte externe ni le schéma.
    public_base_url: str = "http://localhost:5173"

    # Probe
    probe_result_rate_limit: str = "30/minute"
    probe_heartbeat_interval_seconds: int = 30

    # Data retention
    data_retention_days: int = 90  # 0 = keep forever

    # Hourly rollups (plan V2, A-2) — pre-aggregation of check_results.
    # Disabling only stops the builder; nothing reads the table yet (A-3).
    rollup_enabled: bool = True
    rollup_interval_seconds: int = 300
    # Hours folded per run: caps how much raw data one iteration reads, and
    # therefore how fast an initial backfill catches up (168 h = a week per run).
    rollup_max_buckets_per_run: int = 168
    # Hours rebuilt behind the watermark, to fold in results that arrived after
    # their hour closed.
    rollup_recompute_hours: int = 3

    # OIDC / SSO
    oidc_enabled: bool = False
    oidc_issuer_url: str = ""  # e.g. https://accounts.google.com
    oidc_client_id: str = ""
    oidc_client_secret: str = ""
    oidc_redirect_uri: str = ""  # full callback URL; auto-derived if empty
    oidc_scopes: str = "openid email profile"
    # If True, create a new local account on first OIDC login (invite-only = False)
    oidc_auto_provision: bool = True

    # Web Push (VAPID)
    # Generate keys:
    #   python -c "from py_vapid import Vapid; v=Vapid(); v.generate_keys();
    #              print('Private:', v.private_key); print('Public:', v.public_key_urlsafe)"
    vapid_private_key: str = ""  # PEM string or base64url private key
    vapid_public_key: str = ""  # base64url public key — sent to frontend
    vapid_contact_email: str = "admin@example.com"

    # Observability — when set, /api/metrics requires `Authorization: Bearer <token>`.
    # Left empty by default: deployments already gate /api/metrics at the reverse
    # proxy (see SECURITY.md §8); set this for defence-in-depth.
    metrics_auth_token: str = ""

    # Feature flags
    registration_open: bool = True  # False = invite-only after first user

    # V2-02-01 — Network intelligence (probe ASN enrichment).
    # Provider for IP -> ASN/AS-name lookups. "cymru" = Team Cymru DNS service
    # (free, no API key, ~50ms per lookup). "disabled" = skip enrichment entirely.
    asn_lookup_provider: str = "cymru"
    # Hours between automatic refresh of ProbeEnrichment data.
    asn_refresh_hours: int = 24

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
                    'Generate one with: python -c "from cryptography.fernet import Fernet; '
                    'print(Fernet.generate_key().decode())"'
                )
            # Validate Fernet key format early to avoid runtime surprises
            try:
                from cryptography.fernet import Fernet

                Fernet(self.fernet_key.encode())
            except Exception as exc:
                raise ValueError(f"FERNET_KEY is invalid: {exc}") from exc
            for idx, key in enumerate(self.fernet_previous_keys, start=1):
                try:
                    from cryptography.fernet import Fernet

                    Fernet(key.encode())
                except Exception as exc:
                    raise ValueError(f"FERNET_KEY_PREVIOUS entry #{idx} is invalid: {exc}") from exc
            if self.trusted_proxy_list == ["*"]:
                raise ValueError(
                    "TRUSTED_PROXY_IPS='*' trusts the X-Forwarded-For header of every "
                    "caller — per-IP rate limits and audit-log source IPs become "
                    "forgeable. Set it to the address(es) of your reverse proxy."
                )
        return self

    @property
    def fernet_previous_keys(self) -> list[str]:
        """Previous Fernet keys (comma-separated env), decryption-only."""
        return [k.strip() for k in self.fernet_key_previous.split(",") if k.strip()]

    @property
    def trusted_proxy_list(self) -> list[str]:
        """Trusted reverse-proxy addresses, as uvicorn's ProxyHeadersMiddleware wants them.

        An empty value means "trust nobody": the peer address is used as-is and
        forwarded headers are ignored entirely.
        """
        return [h.strip() for h in self.trusted_proxy_ips.split(",") if h.strip()]

    @property
    def is_production(self) -> bool:
        return self.environment == "production"


_settings: Settings | None = None


def get_settings() -> Settings:
    global _settings
    if _settings is None:
        _settings = Settings()
    return _settings
