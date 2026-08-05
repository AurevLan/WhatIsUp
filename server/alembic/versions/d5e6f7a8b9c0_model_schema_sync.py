"""Resync the ORM metadata with the actual schema (plan V2, prérequis A-1).

Revision ID: d5e6f7a8b9c0
Revises: c4d5e6f7a8b9
Create Date: 2026-08-05

``alembic revision --autogenerate`` reported 23 differences against a database
migrated to ``c4d5e6f7a8b9`` — none of them intentional. Most were harmless
noise, but noise is exactly what makes the next partitioning work (A-1)
dangerous: a real diff hidden among two dozen false ones does not get noticed.

Seventeen of the twenty-three were fixed in the models alone and need no DDL
(``AuditLog`` / ``MaintenanceWindow`` missing from ``models/__init__.py`` and
therefore absent from ``Base.metadata``; the two PostgreSQL-only ``incidents``
indexes never declared in ``__table_args__``; ``probes.ixp_membership`` typed
``JSON`` in the model while the column is ``jsonb``).

This migration carries the three that do touch the database:

1. **Sixteen dead ``ix_<table>_id`` indexes.** ``UUIDPrimaryKeyMixin`` declared
   ``index=True`` on the primary key, so every table inheriting it minted a
   plain btree on ``id`` alongside the unique btree the PK constraint already
   provides. Never selectable over the PK index, paid for on every insert. Five
   of them were created three commits ago by the on-call migration — the flag
   kept propagating. Removing it from the mixin is what stops the bleeding;
   this drop cleans up what it already produced.

2. **``ix_users_oidc_sub``.** ``users.oidc_sub`` carries both a ``UNIQUE``
   constraint (``uq_users_oidc_sub``, itself backed by a unique btree) and this
   redundant non-unique index. Same column, same access paths.

3. **``monitors.dns_nameservers`` → ``jsonb``.** The model has typed it
   ``JSON().with_variant(JSONB, "postgresql")`` all along, like every other
   JSON column on ``monitors`` — all of which are ``jsonb`` in the database.
   This one alone was created as plain ``json``, so the model and the schema
   disagreed on the storage format. ``json`` keeps the raw text and reparses on
   every read; the cast is safe in both directions and the column holds a small
   list of nameserver strings.

``downgrade()`` recreates all seventeen indexes verbatim and casts the column
back, so the whole thing is reversible.
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "d5e6f7a8b9c0"
down_revision: str | None = "c4d5e6f7a8b9"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# Tables inheriting UUIDPrimaryKeyMixin whose `ix_<table>_id` actually made it
# into the schema. Others inherit the mixin too but predate it or were created
# by hand-written DDL, so they have nothing to drop.
_REDUNDANT_PK_INDEXES: tuple[str, ...] = (
    "alert_channels",
    "alert_rules",
    "escalation_levels",
    "escalation_policies",
    "monitor_groups",
    "monitor_templates",
    "monitors",
    "oncall_overrides",
    "oncall_schedules",
    "probe_groups",
    "probes",
    "tags",
    "teams",
    "user_api_keys",
    "user_contacts",
    "users",
)


def upgrade() -> None:
    for table in _REDUNDANT_PK_INDEXES:
        op.execute(f"DROP INDEX IF EXISTS ix_{table}_id")

    op.execute("DROP INDEX IF EXISTS ix_users_oidc_sub")

    op.execute(
        "ALTER TABLE monitors ALTER COLUMN dns_nameservers TYPE jsonb USING dns_nameservers::jsonb"
    )


def downgrade() -> None:
    op.execute(
        "ALTER TABLE monitors ALTER COLUMN dns_nameservers TYPE json USING dns_nameservers::json"
    )

    op.execute("CREATE INDEX IF NOT EXISTS ix_users_oidc_sub ON users (oidc_sub)")

    for table in _REDUNDANT_PK_INDEXES:
        op.execute(f"CREATE INDEX IF NOT EXISTS ix_{table}_id ON {table} (id)")
