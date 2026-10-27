"""Associate new model tool requests with their originating conversation."""

import sqlalchemy as sa

from alembic import op

revision = "20261027_0005"
down_revision = "20261027_0004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("agent_tool_requests", sa.Column("conversation_id", sa.Uuid(), nullable=True))
    op.create_foreign_key(
        "fk_tool_request_conversation",
        "agent_tool_requests",
        "agent_conversations",
        ["conversation_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_index(
        "ix_agent_tool_requests_conversation_id", "agent_tool_requests", ["conversation_id"]
    )


def downgrade() -> None:
    op.drop_index("ix_agent_tool_requests_conversation_id", table_name="agent_tool_requests")
    op.drop_constraint("fk_tool_request_conversation", "agent_tool_requests", type_="foreignkey")
    op.drop_column("agent_tool_requests", "conversation_id")
