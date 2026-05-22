"""B3 — heartbeat slug becomes per-owner; introduce globally unique heartbeat_token.

The legacy public URL ``/api/v1/ping/{slug}`` relied on a global UNIQUE on
``monitors.heartbeat_slug``, leaking cross-tenant slug usage and forcing
namespace collisions. From this migration onward:

* ``heartbeat_slug`` is unique *per owner* (composite UQ ``(owner_id, slug)``).
* ``heartbeat_token`` is a cryptographically random, globally unique secret —
  it is what routes the public ping endpoint.

Existing monitors with a slug get a freshly generated token; consumers must
re-fetch the monitor (or read the new URL from the UI) before calling
``/api/v1/ping/{token}``.

Revision ID: v8w9x0y1z2a3
Revises: u7v8w9x0y1z2
Create Date: 2026-05-14
"""

from __future__ import annotations

import secrets
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "v8w9x0y1z2a3"
down_revision: str | None = "u7v8w9x0y1z2"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    bind = op.get_bind()

    # 1. Add heartbeat_token (nullable while we backfill)
    op.add_column("monitors", sa.Column("heartbeat_token", sa.String(length=64), nullable=True))

    # 2. Backfill tokens for every monitor that already declares a slug.
    #    A token MUST be globally unique, so we generate one per row in Python
    #    (rather than relying on a database UDF that may not be available).
    rows = bind.execute(
        sa.text(
            "SELECT id FROM monitors WHERE heartbeat_slug IS NOT NULL AND heartbeat_token IS NULL"
        )
    ).fetchall()
    for row in rows:
        bind.execute(
            sa.text("UPDATE monitors SET heartbeat_token = :tok WHERE id = :id"),
            {"tok": secrets.token_urlsafe(32), "id": row[0]},
        )

    # 3. Unique index on heartbeat_token (after backfill, so NULLs are allowed)
    op.create_index("ix_monitors_heartbeat_token", "monitors", ["heartbeat_token"], unique=True)

    # 4. Drop the legacy global UNIQUE on heartbeat_slug.
    #    The original add_column created an auto-named constraint on Postgres
    #    (``monitors_heartbeat_slug_key``); on SQLite the unique was inlined in
    #    the column definition so there is nothing explicit to drop.
    if bind.dialect.name == "postgresql":
        op.execute("ALTER TABLE monitors DROP CONSTRAINT IF EXISTS monitors_heartbeat_slug_key")
        # Defensive: the explicit index was dropped in 283efc2c973a but some
        # environments may still carry it.
        op.execute("DROP INDEX IF EXISTS ix_monitors_heartbeat_slug")

    # 5. Composite UQ — slug is now per-owner.
    op.create_unique_constraint(
        "uq_monitors_owner_heartbeat_slug",
        "monitors",
        ["owner_id", "heartbeat_slug"],
    )


def downgrade() -> None:
    op.drop_constraint("uq_monitors_owner_heartbeat_slug", "monitors", type_="unique")

    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        # Best-effort restore of the legacy global UNIQUE. Will fail if cross-
        # tenant slug collisions exist — operators should resolve those first.
        op.execute(
            "ALTER TABLE monitors "
            "ADD CONSTRAINT monitors_heartbeat_slug_key UNIQUE (heartbeat_slug)"
        )

    op.drop_index("ix_monitors_heartbeat_token", table_name="monitors")
    op.drop_column("monitors", "heartbeat_token")
