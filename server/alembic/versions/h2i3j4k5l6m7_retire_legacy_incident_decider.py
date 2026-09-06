"""Retire the legacy per-probe decider — plan Cap v2 4b.

The Global Health Engine is now the only detection engine
(``services/incident.process_check_result`` no longer has a per-probe
fallback branch). Two things follow:

1. ``monitors.health_engine_enabled`` server-side default flips to ``true``,
   so paths that build a ``Monitor`` without going through
   ``schemas.monitor.MonitorCreate`` (JSON import, IaC ``config_sync``) also
   get the engine — there is no other detection path to fall back to.
2. Every remaining monitor with ``health_engine_enabled=false`` (in
   production: exactly one, ``sieau``, created after the M5 bulk migration
   and never caught up) is flipped, and given a default ``quorum_down``
   ``SLORule`` (``min_probes=1``, matching the MonitorCreate default from
   plan Cap v2 4a) if it doesn't already carry an active rule. Never one
   without the other — a monitor must not end up with the engine on and zero
   active rule (CLAUDE.md "Health Engine V2" pitfall #1).

The data migration (see
``whatisup.scripts.migrate_to_health_engine.provision_missing_health_engine_coverage``)
is idempotent: it only touches rows still at ``health_engine_enabled=false``,
so re-running it (or replaying this migration's ``upgrade()`` against an
already-migrated database) is a no-op.

Also drops ``monitors.flap_threshold`` / ``flap_window_minutes``: the only
code that ever read them (``incident_decider.is_flapping``) was the decider
this migration retires. The Health Engine's quorum window
(``SLORule.window_seconds``) and ``cooldown_seconds`` play the equivalent
damping role now — see CLAUDE.md "Health Engine V2 — ops prod".

``downgrade()`` restores the schema (column defaults, flap columns) but does
not attempt to undo the data migration: reverting which monitors were
already-True vs freshly-flipped isn't recoverable, and re-silencing a
monitor by flipping it back to a decider that no longer exists would be
worse than leaving it on the engine.

Revision ID: h2i3j4k5l6m7
Revises: g1h2i3j4k5l6
Create Date: 2026-09-06
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

from whatisup.scripts.migrate_to_health_engine import provision_missing_health_engine_coverage

revision = "h2i3j4k5l6m7"
down_revision = "g1h2i3j4k5l6"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Data migration first, while the column can still distinguish "already
    # migrated" from "still on the legacy decider" via its per-row value —
    # the server_default change below only affects future inserts.
    bind = op.get_bind()
    migrated = provision_missing_health_engine_coverage(bind)
    if migrated:
        print(f"plan Cap v2 4b: migrated {migrated} monitor(s) off the legacy decider")

    op.alter_column(
        "monitors",
        "health_engine_enabled",
        server_default=sa.text("true"),
    )

    op.drop_column("monitors", "flap_threshold")
    op.drop_column("monitors", "flap_window_minutes")


def downgrade() -> None:
    op.add_column(
        "monitors",
        sa.Column("flap_threshold", sa.Integer(), nullable=False, server_default="5"),
    )
    op.add_column(
        "monitors",
        sa.Column("flap_window_minutes", sa.Integer(), nullable=False, server_default="10"),
    )

    op.alter_column(
        "monitors",
        "health_engine_enabled",
        server_default=sa.text("false"),
    )
