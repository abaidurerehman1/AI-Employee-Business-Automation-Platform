"""Message templates, delivery records, events and suppressions."""
import sqlalchemy as sa
from alembic import op

revision = "20261028_0011"
down_revision = "20261027_0010"
branch_labels = None
depends_on = None


def common():
    return [sa.Column("id", sa.Uuid(), primary_key=True), sa.Column("organization_id", sa.Uuid(), sa.ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False)]


def created():
    return sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now())


def upgrade():
    op.create_table("message_templates", *common(), sa.Column("name", sa.String(120), nullable=False), sa.Column("channel", sa.String(10), nullable=False), sa.Column("subject", sa.String(200), nullable=False), sa.Column("body", sa.Text(), nullable=False), created())
    op.create_table("outbound_messages", *common(), sa.Column("created_by", sa.Uuid(), sa.ForeignKey("users.id"), nullable=False), sa.Column("channel", sa.String(10), nullable=False), sa.Column("recipient", sa.String(320), nullable=False), sa.Column("subject", sa.String(200), nullable=False), sa.Column("body", sa.Text(), nullable=False), sa.Column("status", sa.String(30), nullable=False), sa.Column("provider_id", sa.String(200)), sa.Column("idempotency_key", sa.String(120), nullable=False), sa.Column("attempt_count", sa.Integer(), nullable=False), sa.Column("started_at", sa.DateTime(timezone=True)), sa.Column("error_message", sa.Text()), created(), sa.UniqueConstraint("organization_id", "idempotency_key"))
    op.create_table("message_suppressions", *common(), sa.Column("channel", sa.String(10), nullable=False), sa.Column("recipient", sa.String(320), nullable=False), sa.Column("reason", sa.String(40), nullable=False), created(), sa.UniqueConstraint("organization_id", "channel", "recipient"))
    op.create_table("message_events", *common(), sa.Column("message_id", sa.Uuid(), sa.ForeignKey("outbound_messages.id", ondelete="SET NULL")), sa.Column("provider", sa.String(20), nullable=False), sa.Column("event_id", sa.String(200), nullable=False), sa.Column("kind", sa.String(40), nullable=False), sa.Column("content", sa.Text()), created(), sa.UniqueConstraint("provider", "event_id"))
    for name in ("message_templates", "outbound_messages", "message_suppressions", "message_events"):
        op.create_index(f"ix_{name}_organization_id", name, ["organization_id"])
    op.create_index("ix_outbound_messages_provider_id", "outbound_messages", ["provider_id"])


def downgrade():
    for name in ("message_events", "message_suppressions", "outbound_messages", "message_templates"):
        op.drop_table(name)
