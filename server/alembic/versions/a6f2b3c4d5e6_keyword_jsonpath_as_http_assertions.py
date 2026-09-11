"""keyword/json_path become http assertions — plan cap v2, 6f-2 (F5).

``keyword`` and ``json_path`` were never really distinct ways of observing a
service — they were assertions on an HTTP response (a keyword in the body, a
value at a JSON path), implemented from day one *inside* the ``http``
checker (``probe/whatisup_probe/checkers/http.py``, ``HTTPChecker.aliases =
["keyword", "json_path"]``). Promoting them to full ``check_type`` values
cost the picker two tiles for a distinction the operator never needed to
make: "I'm monitoring a URL, and incidentally checking its content."

``Monitor.keyword``/``keyword_negate``/``expected_json_path``/
``expected_json_value`` are untouched by this migration — no column is
added, renamed or dropped. They become optional fields available on any
``http`` monitor (surfaced in the frontend behind a collapsible
"Assertions" panel) instead of being gated behind a dedicated check_type.
``monitors.check_type`` has always been a plain ``String(20)`` (see
``m7n8o9p0q1r2``'s udp/composite cut for the same observation) — there is no
``ALTER TYPE ... DROP VALUE`` dance here, this is a data migration plus an
application-level enum shrink (``models/monitor.py::CheckType``).

**Data safety**: 1 live ``keyword`` monitor on the real instance
(2026-09-11), 0 ``json_path``. Unlike the udp/composite cut, this one is
lossless forward — there is no "no sane conversion" problem here, so
``upgrade()`` migrates data instead of refusing to run: every monitor with
``check_type`` in ``('keyword', 'json_path')`` is repointed to ``http``,
keeping every other column — including its assertion fields — exactly as
they were. The keyword monitor above keeps checking the exact same thing
after this migration: same URL, same keyword, same negate flag.

``downgrade()`` is necessarily a heuristic: once a monitor is ``http``, a
future edit could set *both* ``keyword`` and ``expected_json_path`` at once
(exactly the new capability this lot adds) — a combination the two-type
model never allowed and can't represent going back. It infers the pre-
migration type from which assertion field is populated: ``expected_json_path``
set → ``json_path`` (this also preserves a ``keyword`` set alongside it,
since the pre-6f-2 ``http`` checker already evaluated ``keyword`` regardless
of ``check_type`` — only the json_path fields were gated on
``check_type == "json_path"``); otherwise ``keyword`` set → ``keyword``;
otherwise the monitor stays ``http`` (it never was one of the two retired
types, or carries no assertion to infer from).

Revision ID: a6f2b3c4d5e6
Revises: o9p0q1r2s3t4
Create Date: 2026-09-11
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "a6f2b3c4d5e6"
down_revision: str | None = "o9p0q1r2s3t4"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _retype_keyword_and_json_path_monitors(bind: sa.engine.Connection) -> None:
    """Forward migration, extracted so tests can call it directly against a
    plain connection without spinning up an Alembic ``Operations`` context."""
    bind.execute(
        sa.text(
            "UPDATE monitors SET check_type = 'http' WHERE check_type IN ('keyword', 'json_path')"
        )
    )


def _restore_keyword_and_json_path_check_types(bind: sa.engine.Connection) -> None:
    """Best-effort reverse of the above — see module docstring for why this
    can't always be exact once new http monitors mix both assertion kinds."""
    # json_path first: a monitor with expected_json_path set — with or
    # without a keyword alongside it — must become json_path, since the
    # pre-6f-2 checker only gated the json_path fields on check_type, never
    # the keyword one.
    bind.execute(
        sa.text(
            "UPDATE monitors SET check_type = 'json_path' "
            "WHERE check_type = 'http' "
            "AND expected_json_path IS NOT NULL AND expected_json_path != ''"
        )
    )
    # Whatever is left with a keyword set was either an original keyword
    # monitor, or a new http monitor using only the keyword assertion —
    # both map cleanly onto the old keyword type.
    bind.execute(
        sa.text(
            "UPDATE monitors SET check_type = 'keyword' "
            "WHERE check_type = 'http' AND keyword IS NOT NULL AND keyword != ''"
        )
    )


def upgrade() -> None:
    _retype_keyword_and_json_path_monitors(op.get_bind())


def downgrade() -> None:
    _restore_keyword_and_json_path_check_types(op.get_bind())
