"""CODE-2: CheckResultOut must expose the waterfall timing breakdown.

`dns_resolve_ms` / `ttfb_ms` / `download_ms` are produced by the probe and
stored on every HTTP check, but were missing from the response schema — so
the frontend waterfall bar never rendered.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from types import SimpleNamespace

from whatisup.models.result import CheckStatus
from whatisup.schemas.result import CheckResultOut


def _row(**overrides) -> SimpleNamespace:
    base = dict(
        id=uuid.uuid4(),
        monitor_id=uuid.uuid4(),
        probe_id=uuid.uuid4(),
        checked_at=datetime.now(UTC),
        status=CheckStatus.up,
        http_status=200,
        response_time_ms=123.0,
        redirect_count=0,
        final_url=None,
        ssl_valid=None,
        ssl_expires_at=None,
        ssl_days_remaining=None,
        error_message=None,
        dns_resolve_ms=12,
        ttfb_ms=88,
        download_ms=20,
    )
    base.update(overrides)
    return SimpleNamespace(**base)


def test_check_result_out_exposes_timing_breakdown() -> None:
    out = CheckResultOut.model_validate(_row())
    dumped = out.model_dump()
    assert dumped["dns_resolve_ms"] == 12
    assert dumped["ttfb_ms"] == 88
    assert dumped["download_ms"] == 20


def test_check_result_out_timing_defaults_to_none() -> None:
    # TCP/DNS checks have no HTTP waterfall — fields stay null, never absent.
    out = CheckResultOut.model_validate(
        _row(dns_resolve_ms=None, ttfb_ms=None, download_ms=None)
    )
    dumped = out.model_dump()
    assert dumped["dns_resolve_ms"] is None
    assert dumped["ttfb_ms"] is None
    assert dumped["download_ms"] is None
