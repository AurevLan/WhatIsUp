"""Escalade absorbe le renotify — plan cap v2, 6e (F2).

Two timed re-notification mechanisms answered the same question — "what
happens if nobody acknowledges" — with two tables and two background loops:
``AlertRule.renotify_after_minutes`` (+ ``services/renotify.py``) re-paged a
rule's *own* channels on a timer; an escalation ladder (B-1/B-2) pages
*different* targets in order. A one-rung ladder whose rung targets the rule's
own channel and repeats indefinitely is exactly what renotify did — see
``services/escalation.py``'s module docstring for the full argument.

Data safety: measured at 0/12 live rules on the real instance (2026-09-08),
but this migration still carries every ``renotify_after_minutes`` value
forward rather than dropping it, in case another deployment has some — same
posture as ``n8o9p0q1r2s3``.

For every ``alert_rules`` row with ``renotify_after_minutes IS NOT NULL`` and
no ladder already attached (``escalation_policy_id IS NULL`` — a rule that
already carries a ladder keeps it untouched, and simply loses the now-
redundant renotify value), this creates or reuses one ``escalation_policies``
row per ``(owner_id, renotify_after_minutes, channel set)`` — reusing rather
than minting a twin for every rule that shares the same cadence and channels,
scoped by owner so two tenants that happen to share a channel-id shape never
end up sharing a policy — with:

- one ``escalation_levels`` rung per channel the rule had, ``target_type =
  'channel'``: the level model pages exactly one target per rung, so a rule
  with several channels becomes several rungs. Only the first rung's
  ``delay_minutes`` is the old ``renotify_after_minutes`` value; every rung
  after it has ``delay_minutes = 0`` (fires on the very next escalation tick,
  ~30s later), so all of the rule's channels are paged within one tick of
  each other — the closest a single-target-per-rung ladder can get to
  "notify every one of these channels at once".
- ``repeat_count = RENOTIFY_FOREVER_REPEAT_COUNT`` (``models/oncall.py``,
  100000). The engine's own ladder-replay field is the only way to express
  "keep paging forever" (there is no separate sentinel for it). This constant
  is also the write schemas' upper bound (``schemas/oncall.py``) — not a
  smaller UI-only cap — precisely so a policy built here can still be PATCHed
  afterwards: an earlier draft of this migration used a bare ``100_000``
  local to this file while ``EscalationPolicyUpdate.repeat_count`` stayed
  capped at ``le=10``, which made the migrated policy pass every read but
  fail *any* PATCH against it (even one that left ``repeat_count`` alone —
  Pydantic validates the whole model) with an opaque 422. 100000 replays is,
  for any operationally meaningful incident lifetime, indistinguishable from
  "forever" while remaining a plain bounded integer the existing engine
  already knows how to walk — never more silent than the loop it replaces.

Every migration-created policy's name is prefixed with ``[6e] `` so
``downgrade()`` can find its own rows again without guessing (and so a human
reading the escalation-policy list can tell where it came from).

Also scrubs ``renotify_after_minutes`` out of every ``alert_matrix_templates``
row's ``rows`` JSON (seeded once, at migration ``v7w8x9y0z1a2``, and frozen in
the database ever since — editing the Python catalog in
``services/alert_matrix_templates.py`` does not touch data already written).
Left behind, that key survives into the payload the moment someone applies
one of the built-in templates from the alert matrix UI — and ``AlertMatrixRow``
(``schemas/alert.py``) forbids extra fields, so that payload would now 422.
This is not optional cleanup; it is what keeps "apply a system template"
working at all after this migration.

Revision ID: o9p0q1r2s3t4
Revises: n8o9p0q1r2s3
Create Date: 2026-09-08
"""

from __future__ import annotations

import json
import uuid
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

from whatisup.models.oncall import RENOTIFY_FOREVER_REPEAT_COUNT

revision: str = "o9p0q1r2s3t4"
down_revision: str | None = "n8o9p0q1r2s3"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_MIGRATION_MARKER = "[6e] "


def upgrade() -> None:
    bind = op.get_bind()

    rules = bind.execute(
        sa.text(
            """
            SELECT id, owner_id, renotify_after_minutes
            FROM alert_rules
            WHERE renotify_after_minutes IS NOT NULL
              AND escalation_policy_id IS NULL
            """
        )
    ).fetchall()

    # (owner_id, renotify_after_minutes, channel_ids) -> policy_id. Keyed by
    # owner too: two tenants whose rules happen to reference the same channel
    # ids (impossible in practice — channels are tenant-scoped — but never
    # assume that from a data migration) must never end up sharing a policy.
    policy_cache: dict[tuple[uuid.UUID, int, tuple[uuid.UUID, ...]], uuid.UUID] = {}

    for rule_id, owner_id, minutes in rules:
        channel_ids = [
            row[0]
            for row in bind.execute(
                sa.text(
                    "SELECT channel_id FROM alert_rule_channels "
                    "WHERE rule_id = :rule_id ORDER BY channel_id"
                ),
                {"rule_id": rule_id},
            ).fetchall()
        ]
        if not channel_ids:
            # No channel to page: the old renotify loop's dispatch loop iterated
            # an empty list and did nothing. No ladder is needed for the same
            # (already silent) outcome.
            continue

        cache_key = (owner_id, minutes, tuple(channel_ids))
        policy_id = policy_cache.get(cache_key)
        if policy_id is None:
            policy_id = uuid.uuid4()
            bind.execute(
                sa.text(
                    """
                    INSERT INTO escalation_policies
                        (id, owner_id, team_id, name, description, repeat_count,
                         enabled, created_at, updated_at)
                    VALUES
                        (:id, :owner_id, NULL, :name, :description, :repeat_count,
                         true, now(), now())
                    """
                ),
                {
                    "id": policy_id,
                    "owner_id": owner_id,
                    "name": f"{_MIGRATION_MARKER}Renotify {minutes} min",
                    "description": (
                        "Politique générée automatiquement (plan cap v2, 6e) pour "
                        "reproduire l'ancien re-notify : mêmes canaux, toutes les "
                        f"{minutes} minutes, jusqu'à acquittement."
                    ),
                    "repeat_count": RENOTIFY_FOREVER_REPEAT_COUNT,
                },
            )
            for position, channel_id in enumerate(channel_ids):
                bind.execute(
                    sa.text(
                        """
                        INSERT INTO escalation_levels
                            (id, policy_id, position, delay_minutes, target_type,
                             target_channel_id, target_schedule_id, target_user_id,
                             created_at, updated_at)
                        VALUES
                            (:id, :policy_id, :position, :delay_minutes, 'channel',
                             :channel_id, NULL, NULL, now(), now())
                        """
                    ),
                    {
                        "id": uuid.uuid4(),
                        "policy_id": policy_id,
                        "position": position,
                        # Only the first rung waits; the rest fire on the very
                        # next tick — see module docstring.
                        "delay_minutes": minutes if position == 0 else 0,
                        "channel_id": channel_id,
                    },
                )
            policy_cache[cache_key] = policy_id

        bind.execute(
            sa.text("UPDATE alert_rules SET escalation_policy_id = :policy_id WHERE id = :rule_id"),
            {"policy_id": policy_id, "rule_id": rule_id},
        )

    op.drop_column("alert_rules", "renotify_after_minutes")

    # See module docstring: strip the same key out of every saved matrix
    # template's rows, system or user-created — otherwise applying one from
    # the UI resends a now-forbidden field and the matrix save 422s.
    for tpl_id, rows in bind.execute(sa.text("SELECT id, rows FROM alert_matrix_templates")):
        if not rows:
            continue
        cleaned = [{k: v for k, v in row.items() if k != "renotify_after_minutes"} for row in rows]
        if cleaned != rows:
            bind.execute(
                sa.text(
                    "UPDATE alert_matrix_templates SET rows = CAST(:rows AS JSONB) WHERE id = :id"
                ),
                {"rows": json.dumps(cleaned), "id": tpl_id},
            )


def downgrade() -> None:
    op.add_column("alert_rules", sa.Column("renotify_after_minutes", sa.Integer(), nullable=True))

    bind = op.get_bind()

    # Restore renotify_after_minutes from the migration-created policy's first
    # rung's delay, then detach the rule from the ladder — mirrors the shape
    # upgrade() built. A policy a human renamed since (dropping the marker)
    # or hand-edited beyond recognition is left as a real ladder rather than
    # guessed apart — the same kind of narrowing n8o9p0q1r2s3's downgrade
    # already accepts for data outside the migration's own guarantees.
    bind.execute(
        sa.text(
            """
            UPDATE alert_rules
            SET renotify_after_minutes = el.delay_minutes,
                escalation_policy_id = NULL
            FROM escalation_policies ep
            JOIN escalation_levels el ON el.policy_id = ep.id AND el.position = 0
            WHERE alert_rules.escalation_policy_id = ep.id
              AND ep.name LIKE :marker
            """
        ),
        {"marker": f"{_MIGRATION_MARKER}%"},
    )

    # Every policy this migration created is now unreferenced by the rules it
    # was built for. ON DELETE SET NULL on alert_rules.escalation_policy_id
    # (see models/alert.py) covers a rule a human later pointed at one of
    # these by hand — it simply degrades to the legacy fan-out, same as
    # detaching any other policy.
    bind.execute(
        sa.text(
            "DELETE FROM escalation_levels WHERE policy_id IN "
            "(SELECT id FROM escalation_policies WHERE name LIKE :marker)"
        ),
        {"marker": f"{_MIGRATION_MARKER}%"},
    )
    bind.execute(
        sa.text("DELETE FROM escalation_policies WHERE name LIKE :marker"),
        {"marker": f"{_MIGRATION_MARKER}%"},
    )

    # The `renotify_after_minutes` values scrubbed from alert_matrix_templates
    # rows are not restored: upgrade() didn't keep a copy, and reconstructing
    # them would mean guessing whether a since-edited template still matches
    # what v7w8x9y0z1a2 originally seeded. Accepted narrowing, same posture as
    # n8o9p0q1r2s3's downgrade for data outside the migration's own
    # guarantees — the column comes back, the matrix UI keeps working (no
    # extra key to trip `extra="forbid"` either way), only the specific old
    # per-template cadence default is gone.
