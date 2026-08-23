"""Pydantic schemas for discovery sources and discovered services (plan D, D-0).

``params`` validation is per-``source_type`` and lives here rather than on the
model: the model stores an opaque JSONB blob, this module is the only place
that knows what shape it must have. ``validate_discovery_params`` is the
single entry point both ``DiscoverySourceIn`` and the update endpoint call —
an update that only touches ``params`` still needs the *existing* source's
``source_type`` to validate against, which only the endpoint has.
"""

from __future__ import annotations

import ipaddress
import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field, model_validator

SourceType = Literal["docker", "port_scan"]

#: A /24 (256 addresses) is the largest CIDR a port_scan source may declare —
#: bounded scan is a non-negotiable (plan_discovery.md § Sécurité), not a knob.
_MIN_PORT_SCAN_PREFIXLEN = 24
_MAX_PORTS = 64


class _PortScanParams(BaseModel):
    model_config = {"extra": "forbid"}

    cidr: str
    ports: list[int] = Field(min_length=1, max_length=_MAX_PORTS)

    @model_validator(mode="after")
    def _validate(self) -> _PortScanParams:
        try:
            network = ipaddress.ip_network(self.cidr, strict=False)
        except ValueError as exc:
            raise ValueError(f"invalid cidr '{self.cidr}': {exc}") from exc
        if network.version != 4:
            raise ValueError("cidr must be an IPv4 network (IPv6 discovery is not supported yet)")
        if network.prefixlen < _MIN_PORT_SCAN_PREFIXLEN:
            raise ValueError(f"cidr must be /{_MIN_PORT_SCAN_PREFIXLEN} or smaller (bounded scan)")
        for port in self.ports:
            if not (1 <= port <= 65535):
                raise ValueError(f"port {port} out of range 1-65535")
        return self


class _DockerParams(BaseModel):
    # No parameters required for the first lot — the model_config below still
    # forbids stray keys so a typo is a 422, not a silently ignored field.
    model_config = {"extra": "forbid"}


def validate_discovery_params(source_type: str, params: dict) -> dict:
    """Validate and normalize ``params`` for a given ``source_type``.

    Raises ``ValueError`` (turned into a 422 by the caller) on anything that
    does not fit the declared shape for that source kind.
    """
    if source_type == "docker":
        _DockerParams.model_validate(params)
        return {}
    if source_type == "port_scan":
        return _PortScanParams.model_validate(params).model_dump()
    raise ValueError(f"unknown source_type '{source_type}'")


# ── DiscoverySource ──────────────────────────────────────────────────────────


class DiscoverySourceIn(BaseModel):
    model_config = {"extra": "forbid"}

    team_id: uuid.UUID | None = None
    probe_id: uuid.UUID
    source_type: SourceType
    params: dict = Field(default_factory=dict)
    enabled: bool = True

    @model_validator(mode="after")
    def _check_params(self) -> DiscoverySourceIn:
        self.params = validate_discovery_params(self.source_type, self.params)
        return self


class DiscoverySourceUpdate(BaseModel):
    """``source_type`` is deliberately absent: it is immutable after creation.

    Changing it would invalidate ``params``' meaning in place (a port_scan
    ``cidr``/``ports`` blob is not a valid docker config and vice versa) —
    ``extra="forbid"`` turns an attempt to send it into a clean 422 rather
    than a field that is silently ignored.
    """

    model_config = {"extra": "forbid"}

    team_id: uuid.UUID | None = None
    probe_id: uuid.UUID | None = None
    params: dict | None = None
    enabled: bool | None = None


class DiscoverySourceOut(BaseModel):
    id: uuid.UUID
    owner_id: uuid.UUID
    team_id: uuid.UUID | None
    probe_id: uuid.UUID
    source_type: str
    params: dict
    enabled: bool
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


# ── DiscoveredService ────────────────────────────────────────────────────────


class DiscoverySourceForProbe(BaseModel):
    """Slice of ``DiscoverySource`` handed to the probe that runs it (plan D, D-1).

    No ``owner_id``/``team_id``: the heartbeat already scopes this list to
    ``probe_id == the authenticated probe``, and tenancy is meaningless to the
    process actually running the scan.
    """

    id: uuid.UUID
    source_type: str
    params: dict

    model_config = {"from_attributes": True}


class DiscoveredServiceOut(BaseModel):
    id: uuid.UUID
    source_id: uuid.UUID
    monitor_id: uuid.UUID | None
    host: str
    port: int | None
    proto: str
    normalized_target: str
    hints: dict
    status: str
    first_seen_at: datetime
    last_seen_at: datetime
    status_changed_at: datetime
    created_at: datetime
    updated_at: datetime

    # Pre-filled proposal (plan D, D-2) — never stored, always recomputed from
    # `hints`/`port`/`proto` at serialization time by `services/discovery.py`.
    # Advisory only: accept() applies them only where the caller didn't
    # override the corresponding field.
    suggested_check_type: str
    suggested_name: str
    suggested_group: str | None
    suggested_tags: list[str]
    suggested_alert_matrix_template_id: uuid.UUID | None

    model_config = {"from_attributes": True}


class DiscoveredServiceAcceptIn(BaseModel):
    """Overrides for the monitor D-2's accept() creates from a proposal.

    Every field is optional and, when omitted, falls back to the prefill
    computed from the service's `hints`/`port`/`proto` (see
    `services/discovery.py::default_monitor_fields`) — "l'appelant peut
    surcharger les champs pré-remplis" (plan_discovery.md, D-2 §3).
    """

    model_config = {"extra": "forbid"}

    name: str | None = Field(default=None, min_length=1, max_length=255)
    check_type: str | None = Field(
        default=None,
        pattern=r"^(http|tcp|udp|dns|keyword|json_path|scenario|heartbeat|smtp|ping|domain_expiry|composite)$",
    )
    group_id: uuid.UUID | None = None
    team_id: uuid.UUID | None = None
    tag_ids: list[uuid.UUID] = Field(default_factory=list)
    interval_seconds: int = Field(default=60, ge=5, le=86400)
    # Auto-create default single-condition alert rules (existing CRUD path,
    # `create_monitor`'s `alert_channel_ids`) — ignored when
    # `alert_matrix_template_id` is set, see `apply the AlertMatrixTemplate`
    # branch instead (a monitor must not get both a default preset rule *and*
    # the matching template row for the same condition).
    alert_channel_ids: list[uuid.UUID] = Field(default_factory=list)
    # When set, `alert_channel_ids` is used as the fallback channel list for
    # any template row that doesn't name its own `channel_ids`.
    alert_matrix_template_id: uuid.UUID | None = None
