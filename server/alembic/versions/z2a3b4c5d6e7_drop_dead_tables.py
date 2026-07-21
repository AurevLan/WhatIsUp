"""Drop dead tables ``public_pages`` and ``user_tag_permissions``.

Neither table was ever wired to an endpoint or service:
- ``PublicPage`` — public status pages are served through
  ``MonitorGroup.public_slug`` since day one; the model, its schemas and this
  table were never read or written outside their own definitions.
- ``UserTagPermission`` — per-user tag RBAC that was never branched; tags are
  a global pool with superadmin-only mutation (decision 2026-06-11).

Both tables are empty in any deployment (no code path inserts into them), so
the drop is lossless. Downgrade recreates them exactly as the initial
migration did.

Revision ID: z2a3b4c5d6e7
Revises: y1z2a3b4c5d6
Create Date: 2026-07-21
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "z2a3b4c5d6e7"
down_revision = "y1z2a3b4c5d6"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.drop_index(op.f("ix_public_pages_slug"), table_name="public_pages")
    op.drop_index(op.f("ix_public_pages_id"), table_name="public_pages")
    op.drop_index(op.f("ix_public_pages_group_id"), table_name="public_pages")
    op.drop_table("public_pages")

    op.drop_index("ix_utp_user_id", table_name="user_tag_permissions")
    op.drop_index("ix_utp_tag_id", table_name="user_tag_permissions")
    op.drop_table("user_tag_permissions")
    # The permission_level enum belonged solely to user_tag_permissions.
    sa.Enum(name="permission_level").drop(op.get_bind(), checkfirst=True)


def downgrade() -> None:
    op.create_table(
        "user_tag_permissions",
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("tag_id", sa.Uuid(), nullable=False),
        sa.Column(
            "permission", sa.Enum("view", "edit", "admin", name="permission_level"), nullable=False
        ),
        sa.ForeignKeyConstraint(["tag_id"], ["tags.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("user_id", "tag_id"),
    )
    op.create_index("ix_utp_tag_id", "user_tag_permissions", ["tag_id"], unique=False)
    op.create_index("ix_utp_user_id", "user_tag_permissions", ["user_id"], unique=False)

    op.create_table(
        "public_pages",
        sa.Column("slug", sa.String(length=100), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("group_id", sa.Uuid(), nullable=True),
        sa.Column("custom_domain", sa.String(length=255), nullable=True),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["group_id"], ["monitor_groups.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_public_pages_group_id"), "public_pages", ["group_id"], unique=False)
    op.create_index(op.f("ix_public_pages_id"), "public_pages", ["id"], unique=False)
    op.create_index(op.f("ix_public_pages_slug"), "public_pages", ["slug"], unique=True)
