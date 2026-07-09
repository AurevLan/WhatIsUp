"""Rotate Fernet-encrypted secrets to the current primary FERNET_KEY.

Re-encrypts every value stored at rest with an old Fernet key so it uses the
current primary FERNET_KEY. Old key(s) must still be available through the
FERNET_KEY_PREVIOUS env var (comma-separated) — decryption tries the primary
key first, then each previous key (MultiFernet).

Covered stores (everything encrypted with the global FERNET_KEY):

- ``alert_channels.config``            — secret fields (bot_token, api_key, …)
- ``monitors.scenario_variables``      — entries marked ``secret: true``
- ``users.totp_secret``                — TOTP secrets (pending or active)
- ``system_settings.oidc_client_secret``

The tool is idempotent: values already encrypted with the primary key are left
untouched. Values that no key can decrypt (legacy plaintext, or ciphertext
from an unknown key) are counted as "unreadable" and never modified — and
never printed.

Usage::

    python -m whatisup.tools.rotate_fernet [--dry-run]

Zero-downtime procedure: see SECURITY.md §7 "Rotation FERNET_KEY".
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from dataclasses import dataclass, field

from cryptography.fernet import Fernet, InvalidToken, MultiFernet
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from whatisup.core.config import get_settings
from whatisup.core.database import get_session_factory
from whatisup.core.security import _SECRET_FIELDS
from whatisup.models.alert import AlertChannel
from whatisup.models.monitor import Monitor
from whatisup.models.system_settings import SystemSettings
from whatisup.models.user import User

# Statuses returned by _rotate_value
_CURRENT = "current"  # already encrypted with the primary key — no-op
_ROTATED = "rotated"  # decrypted with an old key, re-encrypted with primary
_UNREADABLE = "unreadable"  # no configured key decrypts it (legacy plaintext?)


@dataclass
class StoreReport:
    """Per-store counters. ``scanned`` counts rows; the rest count values."""

    scanned: int = 0
    rotated: int = 0
    current: int = 0
    unreadable: int = 0


@dataclass
class RotationReport:
    dry_run: bool = False
    stores: dict[str, StoreReport] = field(default_factory=dict)

    @property
    def total_rotated(self) -> int:
        return sum(s.rotated for s in self.stores.values())

    def summary(self) -> str:
        lines = []
        if self.dry_run:
            lines.append("FERNET_KEY rotation — DRY RUN (nothing written)")
        else:
            lines.append("FERNET_KEY rotation — applied")
        for name, s in self.stores.items():
            lines.append(
                f"  {name:38s}: {s.rotated} rotated, {s.current} already current, "
                f"{s.unreadable} unreadable ({s.scanned} rows scanned)"
            )
        verb = "would be rotated" if self.dry_run else "rotated"
        lines.append(f"Total: {self.total_rotated} value(s) {verb}.")
        return "\n".join(lines)


def _rotate_value(value: str, primary: Fernet, multi: MultiFernet) -> tuple[str, str]:
    """Return ``(new_value, status)``. Never raises, never logs the value."""
    try:
        primary.decrypt(value.encode())
        return value, _CURRENT
    except InvalidToken:
        pass
    try:
        # MultiFernet.rotate: decrypt with any key, re-encrypt with the primary.
        return multi.rotate(value.encode()).decode(), _ROTATED
    except InvalidToken:
        return value, _UNREADABLE


def _bump(report: StoreReport, status: str) -> None:
    if status == _ROTATED:
        report.rotated += 1
    elif status == _CURRENT:
        report.current += 1
    else:
        report.unreadable += 1


async def rotate(session: AsyncSession, *, dry_run: bool = False) -> RotationReport:
    """Re-encrypt every Fernet-encrypted value with the primary FERNET_KEY.

    Idempotent. With ``dry_run=True`` nothing is modified nor committed —
    counters report what a real run would do.
    """
    settings = get_settings()
    if not settings.fernet_key:
        raise RuntimeError("FERNET_KEY is not set — nothing to rotate.")
    primary = Fernet(settings.fernet_key.encode())
    multi = MultiFernet([primary, *(Fernet(k.encode()) for k in settings.fernet_previous_keys)])

    report = RotationReport(dry_run=dry_run)

    # -- alert_channels.config (secret fields only) ---------------------------
    store = report.stores.setdefault("alert_channels.config", StoreReport())
    channels = (await session.execute(select(AlertChannel))).scalars().all()
    for channel in channels:
        store.scanned += 1
        config = channel.config or {}
        new_config = dict(config)
        changed = False
        for key, value in config.items():
            if key in _SECRET_FIELDS and isinstance(value, str) and value:
                new_value, status = _rotate_value(value, primary, multi)
                _bump(store, status)
                if status == _ROTATED:
                    new_config[key] = new_value
                    changed = True
        if changed and not dry_run:
            channel.config = new_config

    # -- monitors.scenario_variables (secret: true entries) -------------------
    store = report.stores.setdefault("monitors.scenario_variables", StoreReport())
    monitors = (
        (await session.execute(select(Monitor).where(Monitor.scenario_variables.is_not(None))))
        .scalars()
        .all()
    )
    for monitor in monitors:
        store.scanned += 1
        variables = monitor.scenario_variables or []
        new_variables = []
        changed = False
        for var in variables:
            value = var.get("value")
            if var.get("secret") and isinstance(value, str) and value:
                new_value, status = _rotate_value(value, primary, multi)
                _bump(store, status)
                if status == _ROTATED:
                    var = {**var, "value": new_value}
                    changed = True
            new_variables.append(var)
        if changed and not dry_run:
            monitor.scenario_variables = new_variables

    # -- users.totp_secret -----------------------------------------------------
    store = report.stores.setdefault("users.totp_secret", StoreReport())
    users = (
        (await session.execute(select(User).where(User.totp_secret.is_not(None)))).scalars().all()
    )
    for user in users:
        store.scanned += 1
        if user.totp_secret:
            new_value, status = _rotate_value(user.totp_secret, primary, multi)
            _bump(store, status)
            if status == _ROTATED and not dry_run:
                user.totp_secret = new_value

    # -- system_settings.oidc_client_secret ------------------------------------
    store = report.stores.setdefault("system_settings.oidc_client_secret", StoreReport())
    rows = (await session.execute(select(SystemSettings))).scalars().all()
    for row in rows:
        store.scanned += 1
        if row.oidc_client_secret:
            new_value, status = _rotate_value(row.oidc_client_secret, primary, multi)
            _bump(store, status)
            if status == _ROTATED and not dry_run:
                row.oidc_client_secret = new_value

    # Dry-run never assigns anything, so there is nothing to flush or roll back.
    if not dry_run:
        await session.commit()
    return report


async def _run(dry_run: bool) -> RotationReport:
    factory = get_session_factory()
    async with factory() as session:
        return await rotate(session, dry_run=dry_run)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m whatisup.tools.rotate_fernet",
        description="Re-encrypt Fernet-encrypted DB secrets with the current primary FERNET_KEY.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Report what would be rotated without writing anything.",
    )
    args = parser.parse_args(argv)

    settings = get_settings()
    if not settings.fernet_key:
        print("FERNET_KEY is not set — nothing to rotate.", file=sys.stderr)
        return 2

    report = asyncio.run(_run(dry_run=args.dry_run))
    print(report.summary())
    if any(s.unreadable for s in report.stores.values()):
        print(
            "Warning: some values could not be decrypted with any configured key "
            "(legacy plaintext, or a key missing from FERNET_KEY_PREVIOUS). "
            "They were left untouched.",
            file=sys.stderr,
        )
        # Undecryptable values mean the rotation is NOT complete — never exit 0.
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
