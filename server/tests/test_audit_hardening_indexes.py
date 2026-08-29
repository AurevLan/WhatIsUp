"""Model-side index declarations from the 2026-08 audit hardening pass.

Two of the six findings are pure index changes with no observable behaviour
change on SQLite (the test database), so the only thing worth pinning here is
that the ORM metadata — what ``alembic revision --autogenerate`` compares
against — actually declares what migration ``f97e8cf896cf`` puts in the
database. Getting this wrong would not fail loudly: it would just make
autogenerate propose dropping (or rebuilding with the wrong opclass) an index
nobody remembers exists.
"""

from __future__ import annotations

from whatisup.models.incident import Incident
from whatisup.models.probe_group import probe_group_members


def test_probe_group_members_has_a_probe_id_index() -> None:
    """`probe_id` is the *second* column of the composite PK.

    Three hot paths (probe heartbeat, push_discovery's scope check, the admin
    probe view) filter on `probe_id` alone — a lookup the PK's own btree does
    not serve, since it does not lead with that column.
    """
    by_name = {ix.name: ix for ix in probe_group_members.indexes}
    assert "ix_probe_group_members_probe_id" in by_name
    ix = by_name["ix_probe_group_members_probe_id"]
    assert [c.name for c in ix.columns] == ["probe_id"]


def test_incidents_gin_index_uses_jsonb_ops_not_path_ops() -> None:
    """The opclass must match what `?|` (correlate_common_cause) needs.

    `jsonb_path_ops` only supports `@>`/`@?`/`@@` — a `?|` query planned
    against an index built with it silently falls back to a sequential scan.
    `jsonb_ops` is the one that supports `?|`.
    """
    by_name = {ix.name: ix for ix in Incident.__table__.indexes}
    ix = by_name["ix_incidents_affected_probes_gin"]

    # This is exactly what `alembic revision --autogenerate` diffs against —
    # not the rendered DDL, which (for a text()-expression index rather than a
    # plain column) does not echo the opclass back even though it is applied.
    assert ix.dialect_options["postgresql"]["using"] == "gin"
    ops = ix.dialect_options["postgresql"]["ops"]
    assert ops == {"((affected_probe_ids)::jsonb)": "jsonb_ops"}
