"""Shared dashboard layout and notification read receipts; existing events are reused."""

import sqlalchemy as sa
from alembic import op

revision = "20261028_0016"
down_revision = "20261028_0015"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "dashboard_configurations",
        sa.Column(
            "organization_id",
            sa.Uuid(),
            sa.ForeignKey("organizations.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("industry", sa.String(30), nullable=False),
        sa.Column("widgets", sa.JSON(), nullable=False),
        sa.Column("visible_modules", sa.JSON(), nullable=False),
    )
    op.create_table(
        "notification_receipts",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "organization_id",
            sa.Uuid(),
            sa.ForeignKey("organizations.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "user_id", sa.Uuid(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False
        ),
        sa.Column("notification_key", sa.String(120), nullable=False),
        sa.Column(
            "read_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.UniqueConstraint("organization_id", "user_id", "notification_key"),
    )
    op.create_index(
        "ix_notification_receipts_organization_id", "notification_receipts", ["organization_id"]
    )
    op.create_index("ix_notification_receipts_user_id", "notification_receipts", ["user_id"])


def downgrade():
    op.drop_table("notification_receipts")
    op.drop_table("dashboard_configurations")
