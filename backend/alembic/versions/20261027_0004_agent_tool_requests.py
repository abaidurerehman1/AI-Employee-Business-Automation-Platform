"""Create tool approval records."""

import sqlalchemy as sa

from alembic import op

revision = "20261027_0004"
down_revision = "20261027_0003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "agent_tool_requests",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "organization_id",
            sa.Uuid(),
            sa.ForeignKey("organizations.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "agent_id", sa.Uuid(), sa.ForeignKey("agents.id", ondelete="CASCADE"), nullable=False
        ),
        sa.Column("version_id", sa.Uuid(), sa.ForeignKey("agent_versions.id"), nullable=False),
        sa.Column("requested_by", sa.Uuid(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("decided_by", sa.Uuid(), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("tool_name", sa.String(80), nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("result", sa.Text(), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
    )
    op.create_index(
        "ix_agent_tool_requests_organization_id", "agent_tool_requests", ["organization_id"]
    )


def downgrade() -> None:
    op.drop_table("agent_tool_requests")
