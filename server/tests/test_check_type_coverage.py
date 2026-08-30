"""Contract test: `CheckType` coverage across the server's dispatch points.

`CheckType` is compared as a plain string — never dispatched through a
registry — in at least 7 server files (`schemas/monitor.py`,
`services/discovery.py`, `services/heartbeat.py`, `services/incident.py`,
`api/v1/alerts.py`, `api/v1/probes.py`, `api/v1/monitors/dependencies.py`),
plus the probe-side `checkers/` registry. Adding a new member to the enum
does not force touching any of them.

Most of those sites are a single ``== "composite"`` (or ``== "heartbeat"``)
special case: every *other* member is treated identically by omission from
that branch, which is also the *correct* default for a brand-new type (a new
physical check type should be distributed/dispatched like the existing ones
unless it, too, needs the composite/heartbeat exemption). There is no
"silently missing a branch" risk to gate on a single boolean check like that
— deliberately out of scope here.

Two places really are ``check_type``-keyed registries with a *silent*
fallback for an unlisted key — the same drift class ``services/conditions``
already guards for ``AlertCondition`` (see ``test_condition_registry.py``,
which existed *after* R-1 caught exactly this kind of divergence once):

* ``schemas/monitor.py``'s ``MonitorCreate``/``MonitorUpdate.check_type`` — a
  hand-maintained regex duplicating the enum's membership as a string
  literal. Forget to extend it when adding a ``CheckType`` member and every
  create/update of a monitor with that type 422s, even though the model and
  the probe checker both already support it.
* ``services/alert_presets.ALERT_PRESETS`` (read by ``api/v1/alerts.py``'s
  preset endpoints) — keyed by ``check_type``, with
  ``.get(check_type, ALERT_PRESETS["http"])``. Forget an entry and
  ``GET /alerts/presets/{check_type}`` silently serves *http* presets for the
  new type instead of erroring — nobody notices until the recommended rules
  look wrong for it.

Every assertion below is driven by ``list(CheckType)`` / a parametrization
over it, never a hardcoded list of type names — so a new enum member is
picked up automatically and fails loudly here if either registry wasn't
extended for it.
"""

from __future__ import annotations

import pytest

from whatisup.models.monitor import CheckType
from whatisup.schemas.monitor import MonitorCreate, MonitorUpdate
from whatisup.services.alert_presets import ALERT_PRESETS, get_presets


@pytest.mark.parametrize("check_type", list(CheckType))
def test_monitor_update_pattern_accepts_every_check_type(check_type: CheckType) -> None:
    """``MonitorUpdate.check_type``'s regex must not silently reject a type
    the enum (and the probe) already support."""
    MonitorUpdate(check_type=check_type.value)


@pytest.mark.parametrize("check_type", list(CheckType))
def test_monitor_create_pattern_accepts_every_check_type(check_type: CheckType) -> None:
    """Same contract as above, for ``MonitorCreate`` — plus the one existing
    conditional requirement (``heartbeat`` needs its slug/interval), so this
    doesn't false-fail on an unrelated validator."""
    payload = {
        "name": "contract-test",
        "url": "https://example.com",
        "check_type": check_type.value,
    }
    if check_type == CheckType.heartbeat:
        payload["heartbeat_slug"] = "contract-test"
        payload["heartbeat_interval_seconds"] = 60
    MonitorCreate(**payload)


def test_every_check_type_has_alert_presets() -> None:
    """A `CheckType` member missing from `ALERT_PRESETS` doesn't error — it
    silently serves the *http* presets instead (`get_presets`'s fallback)."""
    missing = [c.value for c in CheckType if c.value not in ALERT_PRESETS]
    assert missing == [], (
        "CheckType member(s) without an ALERT_PRESETS entry — get_presets() "
        f"would silently fall back to the http presets for them: {missing}"
    )


@pytest.mark.parametrize("check_type", list(CheckType))
def test_get_presets_never_substitutes_the_http_fallback(check_type: CheckType) -> None:
    """Belt and braces on top of the membership check: even if a future
    refactor changes how ``get_presets`` reads the dict, a type quietly
    getting someone else's presets must still be caught here."""
    assert get_presets(check_type.value) is ALERT_PRESETS[check_type.value]
