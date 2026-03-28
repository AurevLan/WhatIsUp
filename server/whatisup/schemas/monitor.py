"""Monitor and MonitorGroup schemas."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Literal

from pydantic import AnyHttpUrl, BaseModel, Field, field_validator, model_validator

from whatisup.schemas.tag import TagOut

# ---------------------------------------------------------------------------
# Scenario sub-schemas
# ---------------------------------------------------------------------------

_STEP_TYPES = (
    "navigate|click|fill|type|press|select|submit|hover|scroll|extract"
    "|wait_element|wait_time|assert_text|assert_visible|assert_url|screenshot"
)


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
    interval_seconds: int = Field(default=60, ge=5, le=86400)
    timeout_seconds: int = Field(default=10, ge=1, le=60)
    follow_redirects: bool = True
    expected_status_codes: list[int] = Field(default=[200], min_length=1)
    enabled: bool = True
    ssl_check_enabled: bool = True
    ssl_expiry_warn_days: int = Field(default=30, ge=1, le=365)
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
    # SLO / Error Budget
    slo_target: float | None = Field(None, ge=0.0, le=100.0)
    slo_window_days: int = Field(30, ge=1, le=365)
    # Probe scope
    network_scope: str = Field(default="all", pattern=r"^(all|internal|external)$")
    # Flapping detection — per-monitor overrides
    flap_threshold: int = Field(default=5, ge=2, le=50)
    flap_window_minutes: int = Field(default=10, ge=1, le=60)
    # Auto-alert: channel IDs to auto-create default rules at monitor creation
    alert_channel_ids: list[uuid.UUID] = Field(default=[])

    @field_validator("expected_status_codes")
    @classmethod
    def valid_status_codes(cls, v: list[int]) -> list[int]:
        for code in v:
            if not (100 <= code <= 599):
                raise ValueError(f"Invalid HTTP status code: {code}")
        return v

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
    # SLO / Error Budget
    slo_target: float | None = Field(None, ge=0.0, le=100.0)
    slo_window_days: int | None = Field(None, ge=1, le=365)
    # Probe scope
    network_scope: str | None = Field(default=None, pattern=r"^(all|internal|external)$")
    # Flapping
    flap_threshold: int | None = Field(default=None, ge=2, le=50)
    flap_window_minutes: int | None = Field(default=None, ge=1, le=60)
    # Schema drift
    schema_drift_enabled: bool | None = None


class MonitorOut(BaseModel):
    id: uuid.UUID
    name: str
    url: str
    group_id: uuid.UUID | None
    owner_id: uuid.UUID
    interval_seconds: int
    timeout_seconds: int
    follow_redirects: bool
    expected_status_codes: list[int]
    enabled: bool
    ssl_check_enabled: bool
    ssl_expiry_warn_days: int
    tags: list[TagOut]
    check_type: str
    tcp_port: int | None
    udp_port: int | None = None
    smtp_port: int | None = None
    smtp_starttls: bool = False
    domain_expiry_warn_days: int = 30
    dns_record_type: str | None
    dns_expected_value: str | None
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
    heartbeat_interval_seconds: int | None = None
    heartbeat_grace_seconds: int = 60
    last_heartbeat_at: datetime | None = None
    # Advanced HTTP assertions
    body_regex: str | None = None
    expected_headers: dict[str, str] | None = None
    json_schema: dict | None = None
    # SLO / Error Budget
    slo_target: float | None = None
    slo_window_days: int = 30
    # Probe scope
    network_scope: str = "all"
    # Flapping
    flap_threshold: int = 5
    flap_window_minutes: int = 10
    # Schema drift
    schema_drift_enabled: bool = False
    schema_baseline: str | None = None
    schema_baseline_updated_at: datetime | None = None
    # Runtime fields — populated by list_monitors, not stored in the DB row
    last_status: str | None = None
    uptime_24h: float | None = None

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

    model_config = {"from_attributes": True}


class MonitorGroupCreate(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    description: str | None = None
    public_slug: str | None = Field(
        default=None, min_length=3, max_length=100, pattern=r"^[a-z0-9-]+$"
    )
    tag_ids: list[uuid.UUID] = Field(default=[])


class MonitorGroupUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=255)
    description: str | None = None
    public_slug: str | None = Field(
        default=None, min_length=3, max_length=100, pattern=r"^[a-z0-9-]+$"
    )
    tag_ids: list[uuid.UUID] | None = None


class MonitorGroupOut(BaseModel):
    id: uuid.UUID
    name: str
    description: str | None
    public_slug: str | None
    owner_id: uuid.UUID
    tags: list[TagOut]

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
    action: Literal["enable", "pause", "delete"]


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


class PublicPageCreate(BaseModel):
    slug: str = Field(min_length=3, max_length=100, pattern=r"^[a-z0-9-]+$")
    name: str = Field(min_length=1, max_length=255)
    group_id: uuid.UUID | None = None
    custom_domain: str | None = Field(default=None, max_length=255)


class PublicPageOut(BaseModel):
    id: uuid.UUID
    slug: str
    name: str
    group_id: uuid.UUID | None
    custom_domain: str | None

    model_config = {"from_attributes": True}
