"""Create versioned agents and private conversations."""

import sqlalchemy as sa

from alembic import op

revision = "20261027_0003"
down_revision = "20261027_0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "agents",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "organization_id",
            sa.Uuid(),
            sa.ForeignKey("organizations.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("name", sa.String(120), nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("published_version_id", sa.Uuid(), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
    )
    op.create_index("ix_agents_organization_id", "agents", ["organization_id"])
    op.create_table(
        "agent_versions",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "agent_id", sa.Uuid(), sa.ForeignKey("agents.id", ondelete="CASCADE"), nullable=False
        ),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("role", sa.String(150), nullable=False),
        sa.Column("instructions", sa.Text(), nullable=False),
        sa.Column("tone", sa.String(80), nullable=False),
        sa.Column("language", sa.String(80), nullable=False),
        sa.Column("model", sa.String(100), nullable=False),
        sa.Column("tools", sa.JSON(), nullable=False),
        sa.Column("approval_rules", sa.JSON(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.UniqueConstraint("agent_id", "version"),
    )
    op.create_index("ix_agent_versions_agent_id", "agent_versions", ["agent_id"])
    op.create_table(
        "agent_conversations",
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
        sa.Column(
            "user_id", sa.Uuid(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False
        ),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
    )
    op.create_index(
        "ix_agent_conversations_organization_id", "agent_conversations", ["organization_id"]
    )
    op.create_table(
        "agent_messages",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "conversation_id",
            sa.Uuid(),
            sa.ForeignKey("agent_conversations.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("role", sa.String(16), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
    )
    op.create_index("ix_agent_messages_conversation_id", "agent_messages", ["conversation_id"])


def downgrade() -> None:
    op.drop_table("agent_messages")
    op.drop_table("agent_conversations")
    op.drop_table("agent_versions")
    op.drop_table("agents")
