"""Inbound widget, conversations and webhook deduplication."""
import sqlalchemy as sa
from alembic import op

revision = "20261027_0009"
down_revision = "20261027_0008"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table("inbound_sites", sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("organization_id", sa.Uuid(), sa.ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, unique=True),
        sa.Column("agent_id", sa.Uuid(), sa.ForeignKey("agents.id"), nullable=False),
        sa.Column("name", sa.String(120), nullable=False), sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.Column("webhook_secret", sa.String(128), nullable=False), sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()))
    op.create_index("ix_inbound_sites_organization_id", "inbound_sites", ["organization_id"], unique=True)
    op.create_table("visitor_conversations", sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("organization_id", sa.Uuid(), sa.ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False),
        sa.Column("site_id", sa.Uuid(), sa.ForeignKey("inbound_sites.id", ondelete="CASCADE"), nullable=False),
        sa.Column("token_hash", sa.String(64), nullable=False, unique=True), sa.Column("visitor_name", sa.String(200)),
        sa.Column("visitor_email", sa.String(320)), sa.Column("context", sa.JSON(), nullable=False),
        sa.Column("status", sa.String(20), nullable=False), sa.Column("assigned_to", sa.Uuid(), sa.ForeignKey("users.id", ondelete="SET NULL")),
        sa.Column("lead_id", sa.Uuid(), sa.ForeignKey("crm_leads.id", ondelete="SET NULL")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()))
    for col in ("organization_id", "site_id"):
        op.create_index(f"ix_visitor_conversations_{col}", "visitor_conversations", [col])
    op.create_table("visitor_messages", sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("conversation_id", sa.Uuid(), sa.ForeignKey("visitor_conversations.id", ondelete="CASCADE"), nullable=False),
        sa.Column("role", sa.String(20), nullable=False), sa.Column("content", sa.Text(), nullable=False),
        sa.Column("citations", sa.JSON(), nullable=False), sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()))
    op.create_index("ix_visitor_messages_conversation_id", "visitor_messages", ["conversation_id"])
    op.create_table("inbound_webhook_events", sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("site_id", sa.Uuid(), sa.ForeignKey("inbound_sites.id", ondelete="CASCADE"), nullable=False),
        sa.Column("event_id", sa.String(120), nullable=False), sa.Column("lead_id", sa.Uuid(), sa.ForeignKey("crm_leads.id", ondelete="CASCADE"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("site_id", "event_id"))
    op.create_index("ix_inbound_webhook_events_site_id", "inbound_webhook_events", ["site_id"])


def downgrade():
    for name in ("inbound_webhook_events", "visitor_messages", "visitor_conversations", "inbound_sites"):
        op.drop_table(name)
