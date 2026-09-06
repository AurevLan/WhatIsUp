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

    # Discovery — sticky probe election for group-targeted sources (plan E,
    # E-2 / E-0-2). Cadence of the background re-election loop, and the grace
    # window added to `probe_heartbeat_interval_seconds` before an elected
    # probe is considered dead — same "interval + grace" shape as
    # `Monitor.heartbeat_grace_seconds` (services/heartbeat.py), applied here
    # to a probe's own heartbeat instead of a monitor's ping.
    discovery_election_interval_seconds: int = 60
    discovery_election_grace_seconds: int = 60

    # Data retention. Since A-4 this governs the **raw** check_results only —
    # history beyond it is carried by the rollups, at their own horizon below.
    # Left at 90 days on purpose: shortening it is a per-deployment call (it
    # drops the per-result detail — scenario_result, tls_audit, dns_*, which the
    # rollups do not carry), never something an upgrade should do behind the
    # operator's back.
    data_retention_days: int = 90  # 0 = keep forever
    # Metrics pushed by the tenant's own application (plan V2, C-2). Same
    # horizon as the raw results by default — a pushed metric is raw per-push
    # detail of the same kind. Before C-2 this table was never purged at all,
    # so the first nightly run after upgrading does delete what predates the
    # window; set to 0 to keep the previous keep-forever behaviour.
    metrics_retention_days: int = 90  # 0 = keep forever
    # Discovered services left in a terminal state (chantier D) — `dismissed`
    # (a human said "not this") and `orphaned` (the target vanished from the
    # network) accumulated with no horizon at all before this knob existed
    # (audit finding, 2026-08). Deliberately never touches `proposed` (a
    # pending decision, not yet acted on) or `accepted` (owns a live monitor):
    # this governs stale review-queue clutter only, never a proposal awaiting
    # a human or a monitor's provenance.
    discovered_services_retention_days: int = 90  # 0 = keep forever
    # The notification log (`alert_events`) — one row per dispatch attempt,
    # the one temporal table in the product with no horizon at all before this
    # (audit finding, 2026-08). Every reader of it looks at a short recent
    # window (dedup, storm counters, digest) or at one still-open incident's
    # own events, never at "all events ever" — so ageing out old rows changes
    # nothing observable except how far back an old *resolved* incident's
    # alert history reaches.
    alert_events_retention_days: int = 90  # 0 = keep forever

    # Hourly rollups (plan V2, A-2) — pre-aggregation of check_results, read by
    # services/stats.py since A-3. Disabling stops the builder; stats then fall
    # back to scanning the raw table, and retention loses its safety interlock
    # (see services/retention.py).
    rollup_enabled: bool = True
    rollup_interval_seconds: int = 300
    # Hours folded per run: caps how much raw data one iteration reads, and
    # therefore how fast an initial backfill catches up (168 h = a week per run).
    rollup_max_buckets_per_run: int = 168
    # Hours rebuilt behind the watermark, to fold in results that arrived after
    # their hour closed.
    rollup_recompute_hours: int = 3
    # How long rollups are kept (plan V2, A-4). Longer than the raw window on
    # purpose — outliving it is the entire point of the table. 13 months covers
    # a rolling year plus the month in progress, so a year-on-year comparison
    # never falls off the edge mid-month.
    rollup_retention_months: int = 13  # 0 = keep forever

    # Pushed-metric alerting (plan V2, C-4). Evaluated by a background loop
    # rather than inside POST /metrics on purpose: dispatching an alert means an
    # outbound HTTP call, and putting one on the ingestion path would let a slow
    # webhook throttle the agent that is pushing. The interval is therefore the
    # worst-case alerting delay — lower it if you need to page faster than a
    # minute, at the cost of one extra query per metric rule per run.
    metric_alerts_enabled: bool = True
    metric_alerts_interval_seconds: int = 60

    # Pushed-metric ingestion quotas (plan V2, C-1). Both refuse with 429 rather
    # than dropping quietly: a silently discarded metric is the worst failure a
    # monitoring product can have.
    #
    # Rate is the easy one to reason about — points per minute per monitor.
    # Cardinality is the one that actually protects the database: a single
    # unbounded label (user id, request id) makes the row count a function of
    # what the application observes rather than of how often it pushes, and
    # neither partitioning (C-2) nor retention helps against that.
    metrics_max_points_per_minute: int = 6000  # 0 = unlimited
    metrics_max_series_per_monitor: int = 1000  # 0 = unlimited
    #: Largest accepted batch. Bounds the memory a single request can pin and
    #: keeps one caller from spending a monitor's whole minute in one shot.
    metrics_max_batch_size: int = 1000
    #: Per-point label ceilings. Labels are a dimension, not a payload: a metric
    #: carrying twenty of them is nearly always an event log in disguise.
    metrics_max_labels_per_point: int = 10
    metrics_max_label_key_length: int = 64
    metrics_max_label_value_length: int = 200

    # Leader-loop batch caps (architecture hardening). Several leader-elected
    # background loops used to select their *entire* current backlog in one
    # go — fine in steady state, but after a prolonged Redis outage or a
    # leader-election gap the backlog can pile up (escalation rungs whose
    # `next_fire_at` came due while nobody was running the loop) or simply
    # grow with tenant scale (monitors, incidents, rules, sources). Each loop
    # now caps its per-tick batch, ordered deterministically so whatever
    # doesn't fit this tick is picked up later — same shape as
    # `rollup_max_buckets_per_run` above; nothing is dropped outright.
    # Defaults are generous: they only bite under genuine pathological
    # backlog or fleet size, never in normal operation. The *speed* of
    # draining an oversized backlog differs by loop, per its own docstring:
    # escalation (due-timestamp order), heartbeat (staleness order) and
    # discovery_election (unelected-first order) all make real progress every
    # tick; renotify frees a slot as incidents ack/resolve (normal operation,
    # not a special case). `metric_alerts` is the one exception — no column
    # there naturally advances while a rule stays enabled, so a *sustained*
    # excess keeps the same low-id rules capped until one is
    # disabled/removed — see `evaluate_metric_alerts`'s docstring.
    escalation_max_states_per_run: int = 500
    metric_alerts_max_rules_per_run: int = 1000
    renotify_max_incidents_per_run: int = 1000
    heartbeat_max_monitors_per_run: int = 2000
    discovery_election_max_sources_per_run: int = 500

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
