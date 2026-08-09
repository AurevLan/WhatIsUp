"""Per-incident escalation state (plan V2, B-1).

Revision ID: f5a6b7c8d9e0
Revises: e4f5a6b7c8d9
Create Date: 2026-08-09

B-0 shipped the *shape* of an on-call ladder — policies, levels, rotations,
contacts — and left it inert: ``alert_rules.escalation_policy_id`` was stored
and validated, but nothing in the dispatch path read it. This table is what
turns it on: where one incident currently stands on its ladder.

Persisted rather than kept in memory, for the same reason the digest windows
are: a restart in the middle of a 3 a.m. escalation must not leave an incident
stranded between two rungs, silently un-escalated. An on-call system that
forgets what it was doing when it restarts is worse than one that never
escalated at all, because the operator believes they are covered.

``next_fire_at`` is the entire scheduler. The background loop selects rows whose
turn has come rather than re-deriving every open incident's position, so its
cost tracks the number of *escalating* incidents rather than the number of open
ones.

``incident_id`` is UNIQUE, not merely indexed: two states for one incident would
page twice and advance independently, which is exactly the sort of duplicate
paging that makes people mute a tool.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "f5a6b7c8d9e0"
down_revision: str | None = "e4f5a6b7c8d9"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "escalation_states",
        sa.Column("id", sa.Uuid(as_uuid=True), primary_key=True),
        sa.Column(
            "incident_id",
            sa.Uuid(as_uuid=True),
            sa.ForeignKey("incidents.id", ondelete="CASCADE"),
            nullable=False,
            unique=True,
        ),
        # CASCADE, unlike alert_rules.escalation_policy_id which is SET NULL:
        # a rule outliving its policy degrades to its channels, but an in-flight
        # ladder whose policy just vanished has nothing left to walk.
        sa.Column(
            "policy_id",
            sa.Uuid(as_uuid=True),
            sa.ForeignKey("escalation_policies.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "rule_id",
            sa.Uuid(as_uuid=True),
            sa.ForeignKey("alert_rules.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("next_position", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("repeats_done", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("next_fire_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_fired_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("next_position >= 0", name="ck_escalation_state_position"),
        sa.CheckConstraint("repeats_done >= 0", name="ck_escalation_state_repeats"),
    )
    # The loop's only filter.
    op.create_index("ix_escalation_states_next_fire_at", "escalation_states", ["next_fire_at"])


def downgrade() -> None:
    op.drop_index("ix_escalation_states_next_fire_at", table_name="escalation_states")
    op.drop_table("escalation_states")
