"""Probe country_code — persist the ISO country Cymru already returns.

``services/probe_enrichment.py`` parses ``AS | prefix | country | registry |
allocated`` from Team Cymru's origin TXT record on every enrichment, but the
``country`` field was discarded — there was no column to put it in. The
network verdict's geo axis (``services/network_verdict._country_of``) was
therefore inferring "country" by splitting the operator-entered
``location_name`` free text on the first separator, which produced false
diversity ("Saran, FR" / "Olivet, Loiret, FR" / "Orléans 45000" -> three
distinct fake countries) and false ``network_partition_geo`` verdicts.

Adds ``probes.country_code`` (nullable, 2 chars, ISO-3166-1 alpha-2). Not
indexed: read a handful of rows at a time per incident, never scanned.

Revision ID: g1h2i3j4k5l6
Revises: f97e8cf896cf
Create Date: 2026-08-30
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "g1h2i3j4k5l6"
down_revision = "f97e8cf896cf"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("probes", sa.Column("country_code", sa.String(length=2), nullable=True))


def downgrade() -> None:
    op.drop_column("probes", "country_code")
