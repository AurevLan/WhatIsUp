"""Monitor and MonitorGroup schemas."""

from __future__ import annotations

import json
import re
import uuid
from datetime import datetime
from typing import Literal

from pydantic import AnyHttpUrl, BaseModel, ConfigDict, Field, field_validator, model_validator

from whatisup.core.validators import validate_email_list
from whatisup.schemas.tag import TagOut

# Aligné sur `EmailChannelConfig.to` : au-delà, la liste n'est plus une liste de
# destinataires mais un relais de diffusion.
_MAX_REPORT_EMAILS = 20


def _validate_report_emails(v: list[str] | None) -> list[str] | None:
    """Rejette toute adresse malformée dans `report_emails` (audit F7).

    Ces valeurs sont posées telles quelles dans l'en-tête `To` du rapport SLA :
    sans ce filtre, un CR/LF encapsulé injecte des en-têtes arbitraires (`Bcc`)
    dans un mail émis depuis l'identité SMTP du serveur.
    """
    if v is None:
        return v
    if len(v) > _MAX_REPORT_EMAILS:
        raise ValueError(f"report_emails: at most {_MAX_REPORT_EMAILS} recipients allowed")
    return validate_email_list(v)


# Le probe évalue ce schéma contre le corps de la réponse, avec un budget CPU
# borné (`checkers/_regex_guard.py`, audit F8). Le refuser ici donne un 422 au
# lieu d'un check qui échoue silencieusement à chaque cycle.
_MAX_JSON_SCHEMA_BYTES = 64_000


def _validate_json_schema_size(v: dict | None) -> dict | None:
    if v is None:
        return v
    if len(json.dumps(v)) > _MAX_JSON_SCHEMA_BYTES:
        raise ValueError(f"json_schema: at most {_MAX_JSON_SCHEMA_BYTES} bytes once serialized")
    return v


# ---------------------------------------------------------------------------
# Scenario sub-schemas
# ---------------------------------------------------------------------------

_STEP_TYPES = (
    "navigate|click|fill|type|press|select|submit|hover|scroll|extract"
    "|wait_element|wait_time|assert_text|assert_visible|assert_url|screenshot"
)

# Headers managed by httpx itself — overriding them breaks the request transport
# (Content-Length, Connection) or routing (Host).
_FORBIDDEN_CUSTOM_HEADERS = {"host", "content-length", "connection", "transfer-encoding"}
_HEADER_NAME_RE = re.compile(r"^[A-Za-z0-9-]+$")


def _validate_custom_headers(v: dict[str, str] | None) -> dict[str, str] | None:
    if v is None:
        return v
    if not isinstance(v, dict):
        raise ValueError("custom_headers must be an object of header name → value")
    if len(v) > 20:
        raise ValueError("custom_headers: at most 20 entries allowed")
    for name, value in v.items():
        if not isinstance(name, str) or not isinstance(value, str):
            raise ValueError("custom_headers: keys and values must be strings")
        if not (1 <= len(name) <= 100):
            raise ValueError(f"custom_headers: header name length out of range: {name!r}")
        if not _HEADER_NAME_RE.match(name):
            raise ValueError(f"custom_headers: invalid header name {name!r}")
        if name.lower() in _FORBIDDEN_CUSTOM_HEADERS:
            raise ValueError(f"custom_headers: header {name!r} is reserved and cannot be set")
        if not (1 <= len(value) <= 500):
            raise ValueError(f"custom_headers: value length out of range for {name!r}")
    return v


class ScenarioStep(BaseModel):
    """A single step in a recorded Playwright scenario."""

    type: str = Field(pattern=rf"^({_STEP_TYPES})$")
    label: str = Field(min_length=1, max_length=500)
    params: dict = Field(default_factory=dict)


class ScenarioVariable(BaseModel):
    """A named variable injected into scenario step params via ``{{name}}`` placeholders."""

    name: str = Field(min_length=1, max_length=100, pattern=r"^[a-zA-Z0-9_]+$")
    value: str = Field(max_length=2000)
    secret: bool = False


class MonitorCreate(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    url: AnyHttpUrl
    group_id: uuid.UUID | None = None
    team_id: uuid.UUID | None = None
    interval_seconds: int = Field(default=60, ge=5, le=86400)
    timeout_seconds: int = Field(default=10, ge=1, le=60)
    follow_redirects: bool = True
    expected_status_codes: list[int] = Field(default=[200], min_length=1)
    enabled: bool = True
    ssl_check_enabled: bool = True
    ssl_expiry_warn_days: int = Field(default=30, ge=1, le=365)
    ssl_pin_sha256: str | None = Field(default=None, pattern=r"^[a-f0-9]{64}$")
    ssl_min_chain_days: int | None = Field(default=None, ge=1, le=365)
    tag_ids: list[uuid.UUID] = Field(default=[])
    check_type: str = Field(
        default="http",
        pattern=r"^(http|tcp|udp|dns|keyword|json_path|scenario|heartbeat|smtp|ping|domain_expiry|composite)$",
    )
    tcp_port: int | None = Field(default=None, ge=1, le=65535)
    udp_port: int | None = Field(default=None, ge=1, le=65535)
    smtp_port: int | None = Field(default=None, ge=1, le=65535)
    smtp_starttls: bool = False
    domain_expiry_warn_days: int = Field(default=30, ge=1, le=365)
    dns_record_type: str | None = Field(default=None, pattern=r"^(A|AAAA|CNAME|MX|TXT|NS)$")
    dns_expected_value: str | None = Field(default=None, max_length=512)
    dns_nameservers: list[str] | None = None
    # DNS drift / split baseline
    dns_drift_alert: bool = False
    dns_split_enabled: bool = False
    dns_baseline_ips_internal: list[str] | None = None
    dns_baseline_ips_external: list[str] | None = None
    # Composite monitor
    composite_aggregation: str | None = Field(
        default=None,
        pattern=r"^(majority_up|all_up|any_up|weighted_up)$",
    )
    keyword: str | None = Field(default=None, max_length=512)
    keyword_negate: bool = False
    expected_json_path: str | None = Field(default=None, max_length=512)
    expected_json_value: str | None = Field(default=None, max_length=512)
    scenario_steps: list[ScenarioStep] | None = None
    scenario_variables: list[ScenarioVariable] | None = None
    heartbeat_slug: str | None = Field(default=None, max_length=80, pattern=r"^[a-z0-9\-]+$")
    heartbeat_interval_seconds: int | None = Field(default=None, ge=60)
    heartbeat_grace_seconds: int = Field(default=60, ge=30)
    last_heartbeat_at: datetime | None = None
    # Advanced HTTP assertions
    body_regex: str | None = Field(None, max_length=500)
    expected_headers: dict[str, str] | None = None
    json_schema: dict | None = None
    # Custom request headers sent by the probe (e.g. User-Agent override, auth tokens)
    custom_headers: dict[str, str] | None = None
    # SLO / Error Budget
    slo_target: float | None = Field(None, ge=0.0, le=100.0)
    slo_window_days: int = Field(30, ge=1, le=365)
    # Schema drift detection (API fingerprint computed by the probe)
    schema_drift_enabled: bool = False
    # V2 Global Health Engine — plan Cap v2 4a: on for new monitors. Safe
    # because monitor creation always provisions a matching default SLORule
    # with min_probes=1 (see crud.py), so a single-probe install behaves
    # exactly like the legacy per-probe decider. Existing monitors are
    # untouched — this is a schema default, not a migration.
    health_engine_enabled: bool = True
    # Probe scope
    network_scope: str = Field(default="all", pattern=r"^(all|internal|external)$")
    # Auto-pause after N consecutive failures (None = disabled)
    auto_pause_after: int | None = Field(default=None, ge=2, le=100)
    # Per-monitor data retention override (None = use global default)
    data_retention_days: int | None = Field(default=None, ge=1, le=3650)
    # Runbook — optional incident response procedure
    runbook_enabled: bool = False
    runbook_markdown: str | None = Field(default=None, max_length=20000)
    # Auto-alert: channel IDs to auto-create default rules at monitor creation
    alert_channel_ids: list[uuid.UUID] = Field(default=[])

    @field_validator("expected_status_codes")
    @classmethod
    def valid_status_codes(cls, v: list[int]) -> list[int]:
        for code in v:
            if not (100 <= code <= 599):
                raise ValueError(f"Invalid HTTP status code: {code}")
        return v

    @field_validator("custom_headers")
    @classmethod
    def valid_custom_headers(cls, v: dict[str, str] | None) -> dict[str, str] | None:
        return _validate_custom_headers(v)

    @field_validator("json_schema")
    @classmethod
    def valid_json_schema_size(cls, v: dict | None) -> dict | None:
        return _validate_json_schema_size(v)

    @field_validator("url", mode="before")
    @classmethod
    def url_to_string(cls, v):
        return str(v) if not isinstance(v, str) else v

    @model_validator(mode="after")
    def validate_heartbeat_fields(self) -> MonitorCreate:
        if self.check_type == "heartbeat":
            if not self.heartbeat_slug:
                raise ValueError("heartbeat_slug is required for check_type=heartbeat")
            if not self.heartbeat_interval_seconds:
                raise ValueError("heartbeat_interval_seconds is required for check_type=heartbeat")
        return self


class MonitorUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str | None = Field(default=None, min_length=1, max_length=255)
    url: AnyHttpUrl | None = None
    group_id: uuid.UUID | None = None
    interval_seconds: int | None = Field(default=None, ge=5, le=86400)
    timeout_seconds: int | None = Field(default=None, ge=1, le=60)
    follow_redirects: bool | None = None
    expected_status_codes: list[int] | None = None
    enabled: bool | None = None
    ssl_check_enabled: bool | None = None
    ssl_expiry_warn_days: int | None = Field(default=None, ge=1, le=365)
    ssl_pin_sha256: str | None = Field(default=None, pattern=r"^[a-f0-9]{64}$")
    ssl_min_chain_days: int | None = Field(default=None, ge=1, le=365)
    tag_ids: list[uuid.UUID] | None = None
    check_type: str | None = Field(
        default=None,
        pattern=r"^(http|tcp|udp|dns|keyword|json_path|scenario|heartbeat|smtp|ping|domain_expiry|composite)$",
    )
    tcp_port: int | None = Field(default=None, ge=1, le=65535)
    udp_port: int | None = Field(default=None, ge=1, le=65535)
    smtp_port: int | None = Field(default=None, ge=1, le=65535)
    smtp_starttls: bool | None = None
    domain_expiry_warn_days: int | None = Field(default=None, ge=1, le=365)
    dns_record_type: str | None = Field(default=None, pattern=r"^(A|AAAA|CNAME|MX|TXT|NS)$")
    dns_expected_value: str | None = Field(default=None, max_length=512)
    dns_nameservers: list[str] | None = None
    dns_drift_alert: bool | None = None
    dns_split_enabled: bool | None = None
    dns_baseline_ips_internal: list[str] | None = None
    dns_baseline_ips_external: list[str] | None = None
    composite_aggregation: str | None = Field(
        default=None,
        pattern=r"^(majority_up|all_up|any_up|weighted_up)$",
    )
    keyword: str | None = Field(default=None, max_length=512)
    keyword_negate: bool | None = None
    expected_json_path: str | None = Field(default=None, max_length=512)
    expected_json_value: str | None = Field(default=None, max_length=512)
    scenario_steps: list[ScenarioStep] | None = None
    scenario_variables: list[ScenarioVariable] | None = None
    heartbeat_slug: str | None = Field(default=None, max_length=80, pattern=r"^[a-z0-9\-]+$")
    heartbeat_interval_seconds: int | None = Field(default=None, ge=60)
    heartbeat_grace_seconds: int | None = Field(default=None, ge=30)
    last_heartbeat_at: datetime | None = None
    # Advanced HTTP assertions
    body_regex: str | None = Field(None, max_length=500)
    expected_headers: dict[str, str] | None = None
    json_schema: dict | None = None
    custom_headers: dict[str, str] | None = None
    # SLO / Error Budget
    slo_target: float | None = Field(None, ge=0.0, le=100.0)
    slo_window_days: int | None = Field(None, ge=1, le=365)
    # Probe scope
    network_scope: str | None = Field(default=None, pattern=r"^(all|internal|external)$")
    # Auto-pause after N consecutive failures (None = disabled)
    auto_pause_after: int | None = Field(default=None, ge=2, le=100)
    # Per-monitor data retention override (None = use global default)
    data_retention_days: int | None = Field(default=None, ge=1, le=3650)
    # Schema drift
    schema_drift_enabled: bool | None = None
    # Runbook — toggle + markdown body. When toggled off server-side,
    # runbook_markdown is wiped (option B). See api/v1/monitors.py update logic.
    runbook_enabled: bool | None = None
    runbook_markdown: str | None = Field(default=None, max_length=20000)
    # V2 Global Health Engine — opt-in toggle
    health_engine_enabled: bool | None = None

    @field_validator("custom_headers")
    @classmethod
    def valid_custom_headers(cls, v: dict[str, str] | None) -> dict[str, str] | None:
        return _validate_custom_headers(v)

    @field_validator("json_schema")
    @classmethod
    def valid_json_schema_size(cls, v: dict | None) -> dict | None:
        return _validate_json_schema_size(v)


class MonitorOut(BaseModel):
    id: uuid.UUID
    name: str
    url: str
    group_id: uuid.UUID | None
    owner_id: uuid.UUID
    team_id: uuid.UUID | None = None
    interval_seconds: int
    timeout_seconds: int
    follow_redirects: bool
    expected_status_codes: list[int]
    enabled: bool
    ssl_check_enabled: bool
    ssl_expiry_warn_days: int
    ssl_pin_sha256: str | None = None
    ssl_min_chain_days: int | None = None
    tags: list[TagOut]
    check_type: str
    tcp_port: int | None
    udp_port: int | None = None
    smtp_port: int | None = None
    smtp_starttls: bool = False
    domain_expiry_warn_days: int = 30
    dns_record_type: str | None
    dns_expected_value: str | None
    dns_nameservers: list[str] | None = None
    dns_baseline_ips: list[str] | None = None
    dns_drift_alert: bool = False
    dns_split_enabled: bool = False
    dns_baseline_ips_internal: list[str] | None = None
    dns_baseline_ips_external: list[str] | None = None
    composite_aggregation: str | None = None
    keyword: str | None
    keyword_negate: bool
    expected_json_path: str | None
    expected_json_value: str | None
    scenario_steps: list | None = None
    scenario_variables: list | None = None  # secret values are always masked — see validator below
    heartbeat_slug: str | None = None
    heartbeat_token: str | None = None
    heartbeat_interval_seconds: int | None = None
    heartbeat_grace_seconds: int = 60
    last_heartbeat_at: datetime | None = None
    # Advanced HTTP assertions
    body_regex: str | None = None
    expected_headers: dict[str, str] | None = None
    json_schema: dict | None = None
    custom_headers: dict[str, str] | None = None
    # SLO / Error Budget
    slo_target: float | None = None
    slo_window_days: int = 30
    # Probe scope
    network_scope: str = "all"
    # Auto-pause
    auto_pause_after: int | None = None
    # Per-monitor data retention override
    data_retention_days: int | None = None
    # Schema drift
    schema_drift_enabled: bool = False
    schema_baseline: str | None = None
    schema_baseline_updated_at: datetime | None = None
    # Runbook
    runbook_enabled: bool = False
    runbook_markdown: str | None = None
    # V2 Global Health Engine — opt-in toggle
    health_engine_enabled: bool = True
    # Runtime fields — populated by list_monitors, not stored in the DB row
    last_status: str | None = None
    uptime_24h: float | None = None
    last_response_time_ms: float | None = None
    sparkline: list[float] | None = None
    # plan_cap_v2 §3a — surfaced so the dashboard / monitor list can carry the
    # same network-verdict badge as IncidentsView without a second round trip.
    # `has_open_incident` mirrors it: both were already read by the frontend
    # (stores/monitors.js) but never actually reached the wire — an unknown
    # dict key silently dropped by pydantic's default `extra="ignore"`.
    has_open_incident: bool = False
    network_verdict: str | None = None

    @field_validator("scenario_variables", mode="before")
    @classmethod
    def decrypt_and_mask_secret_variables(cls, v: list | None) -> list | None:
        """Decrypt Fernet-encrypted values, then strip them from the response.

        Secret variable *values* are never returned by the API. Clients must
        re-submit them on update. The ``name`` and ``secret`` flag are preserved
        so the UI can display which variables are configured.
        """
        if not v:
            return v
        from whatisup.core.security import decrypt_scenario_variables

        decrypted = decrypt_scenario_variables(list(v))
        return [
            {**var, "value": ""}  # mask: value exists but is not exposed
            if var.get("secret")
            else var
            for var in decrypted
        ]

    @field_validator("custom_headers", mode="before")
    @classmethod
    def decrypt_custom_header_values(cls, v: dict | None) -> dict | None:
        """Decrypt header values stored under Fernet (audit F18).

        Not masked, unlike secret scenario variables: the edit form reads these
        back and re-submits them, so masking would wipe them on every save.
        """
        if not v:
            return v
        from whatisup.core.security import decrypt_custom_headers

        return decrypt_custom_headers(dict(v))

    model_config = {"from_attributes": True}


class MonitorGroupCreate(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    description: str | None = None
    public_slug: str | None = Field(
        default=None, min_length=3, max_length=100, pattern=r"^[a-z0-9-]+$"
    )
    team_id: uuid.UUID | None = None
    tag_ids: list[uuid.UUID] = Field(default=[])
    custom_logo_url: str | None = Field(default=None, max_length=500)
    accent_color: str | None = Field(default=None, max_length=7, pattern=r"^#[0-9a-fA-F]{6}$")
    announcement_banner: str | None = None
    report_schedule: str | None = Field(default=None, pattern=r"^(weekly|monthly)$")
    report_emails: list[str] | None = None
    public_title: str | None = Field(default=None, max_length=255)
    public_description: str | None = None
    public_logo_url: str | None = Field(default=None, max_length=500)
    public_accent_color: str | None = Field(
        default=None, max_length=7, pattern=r"^#[0-9a-fA-F]{6}$"
    )
    public_custom_css: str | None = None

    @field_validator("report_emails")
    @classmethod
    def valid_report_emails(cls, v: list[str] | None) -> list[str] | None:
        return _validate_report_emails(v)


class MonitorGroupUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str | None = Field(default=None, min_length=1, max_length=255)
    description: str | None = None
    public_slug: str | None = Field(
        default=None, min_length=3, max_length=100, pattern=r"^[a-z0-9-]+$"
    )
    tag_ids: list[uuid.UUID] | None = None
    custom_logo_url: str | None = Field(default=None, max_length=500)
    accent_color: str | None = Field(default=None, max_length=7, pattern=r"^#[0-9a-fA-F]{6}$")
    announcement_banner: str | None = None
    report_schedule: str | None = Field(default=None, pattern=r"^(weekly|monthly)$")
    report_emails: list[str] | None = None
    public_title: str | None = Field(default=None, max_length=255)
    public_description: str | None = None
    public_logo_url: str | None = Field(default=None, max_length=500)
    public_accent_color: str | None = Field(
        default=None, max_length=7, pattern=r"^#[0-9a-fA-F]{6}$"
    )
    public_custom_css: str | None = None

    @field_validator("report_emails")
    @classmethod
    def valid_report_emails(cls, v: list[str] | None) -> list[str] | None:
        return _validate_report_emails(v)


class MonitorGroupOut(BaseModel):
    id: uuid.UUID
    name: str
    description: str | None
    public_slug: str | None
    owner_id: uuid.UUID
    team_id: uuid.UUID | None = None
    tags: list[TagOut]
    custom_logo_url: str | None = None
    accent_color: str | None = None
    announcement_banner: str | None = None
    report_schedule: str | None = None
    report_emails: list[str] | None = None
    public_title: str | None = None
    public_description: str | None = None
    public_logo_url: str | None = None
    public_accent_color: str | None = None
    public_custom_css: str | None = None

    model_config = {"from_attributes": True}


class MonitorDependencyCreate(BaseModel):
    parent_id: uuid.UUID
    suppress_on_parent_down: bool = True


class MonitorDependencyOut(BaseModel):
    id: uuid.UUID
    parent_id: uuid.UUID
    child_id: uuid.UUID
    suppress_on_parent_down: bool

    model_config = {"from_attributes": True}


class BulkActionRequest(BaseModel):
    ids: list[uuid.UUID] = Field(min_length=1, max_length=200)
    action: Literal["enable", "pause", "delete", "set_group", "add_tags", "remove_tags"]
    # Optional payload — required only for the actions that consume it.
    target_group_id: uuid.UUID | None = None  # None on set_group means "ungroup"
    tag_ids: list[uuid.UUID] | None = None  # add_tags / remove_tags


class BulkActionResponse(BaseModel):
    affected: int


class CompositeMonitorMemberCreate(BaseModel):
    monitor_id: uuid.UUID
    weight: int = Field(default=1, ge=1, le=100)
    role: str | None = Field(default=None, max_length=50)


class CompositeMonitorMemberOut(BaseModel):
    id: uuid.UUID
    composite_id: uuid.UUID
    monitor_id: uuid.UUID
    weight: int
    role: str | None

    model_config = {"from_attributes": True}
