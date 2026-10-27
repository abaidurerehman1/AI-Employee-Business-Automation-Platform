"""Persist tool workflow, validation and retry state."""

import sqlalchemy as sa

from alembic import op

revision = "20261027_0007"
down_revision = "20261027_0006"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "agent_tool_requests",
        sa.Column("arguments", sa.JSON(), nullable=False, server_default="{}"),
    )
    op.add_column("agent_tool_requests", sa.Column("call_id", sa.String(200), nullable=True))
    op.add_column(
        "agent_tool_requests", sa.Column("idempotency_key", sa.String(200), nullable=True)
    )
    op.add_column(
        "agent_tool_requests", sa.Column("workflow_id", sa.String(200), nullable=True)
    )
    op.add_column(
        "agent_tool_requests", sa.Column("error_message", sa.Text(), nullable=True)
    )
    op.add_column(
        "agent_tool_requests",
        sa.Column("attempt_count", sa.Integer(), nullable=False, server_default="0"),
    )
    op.add_column(
        "agent_tool_requests", sa.Column("decided_at", sa.DateTime(timezone=True), nullable=True)
    )
    op.add_column(
        "agent_tool_requests",
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_unique_constraint(
        "uq_agent_tool_requests_idempotency_key", "agent_tool_requests", ["idempotency_key"]
    )
    op.create_unique_constraint(
        "uq_agent_tool_requests_workflow_id", "agent_tool_requests", ["workflow_id"]
    )
    op.add_column(
        "agent_messages", sa.Column("source_tool_request_id", sa.Uuid(), nullable=True)
    )
    op.create_foreign_key(
        "fk_agent_messages_source_tool_request",
        "agent_messages",
        "agent_tool_requests",
        ["source_tool_request_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_unique_constraint(
        "uq_agent_messages_source_tool_request",
        "agent_messages",
        ["source_tool_request_id"],
    )


def downgrade() -> None:
    op.drop_constraint(
        "uq_agent_messages_source_tool_request", "agent_messages", type_="unique"
    )
    op.drop_constraint(
        "fk_agent_messages_source_tool_request", "agent_messages", type_="foreignkey"
    )
    op.drop_column("agent_messages", "source_tool_request_id")
    op.drop_constraint("uq_agent_tool_requests_workflow_id", "agent_tool_requests", type_="unique")
    op.drop_constraint(
        "uq_agent_tool_requests_idempotency_key", "agent_tool_requests", type_="unique"
    )
    op.drop_column("agent_tool_requests", "updated_at")
    op.drop_column("agent_tool_requests", "decided_at")
    op.drop_column("agent_tool_requests", "attempt_count")
    op.drop_column("agent_tool_requests", "error_message")
    op.drop_column("agent_tool_requests", "workflow_id")
    op.drop_column("agent_tool_requests", "idempotency_key")
    op.drop_column("agent_tool_requests", "call_id")
    op.drop_column("agent_tool_requests", "arguments")