"""Marketing campaigns, consent, immutable approvals and recipient snapshots.

Templates, delivery messages, suppressions and provider events reuse Phase 9.
Audience and schedule configuration live on campaigns; analytics are derived.
"""
import sqlalchemy as sa
from alembic import op

revision = "20261028_0013"
down_revision = "20261028_0012"
branch_labels = None
depends_on = None


def id_column():
    return sa.Column("id", sa.Uuid(), primary_key=True)


def tenant():
    return sa.Column("organization_id", sa.Uuid(), sa.ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False)


def created():
    return sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False)


def upgrade():
    op.create_table("campaigns", id_column(), tenant(),
        sa.Column("created_by", sa.Uuid(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("approved_by", sa.Uuid(), sa.ForeignKey("users.id")),
        sa.Column("name", sa.String(160), nullable=False), sa.Column("description", sa.Text(), nullable=False),
        sa.Column("channel", sa.String(10), nullable=False), sa.Column("provider", sa.String(20), nullable=False),
        sa.Column("agent_id", sa.Uuid(), sa.ForeignKey("agents.id", ondelete="SET NULL")),
        sa.Column("template_id", sa.Uuid(), sa.ForeignKey("message_templates.id", ondelete="SET NULL")),
        sa.Column("subject", sa.String(200), nullable=False), sa.Column("body", sa.Text(), nullable=False),
        sa.Column("audience", sa.JSON(), nullable=False), sa.Column("timezone", sa.String(80), nullable=False),
        sa.Column("scheduled_at", sa.DateTime(timezone=True)), sa.Column("window_start", sa.Integer(), nullable=False),
        sa.Column("window_end", sa.Integer(), nullable=False), sa.Column("status", sa.String(30), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False), sa.Column("approved_snapshot", sa.JSON()),
        sa.Column("workflow_id", sa.String(150)), sa.Column("error_message", sa.Text()), created(),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False))
    op.create_index("ix_campaigns_organization_id", "campaigns", ["organization_id"])
    op.create_index("ix_campaigns_status", "campaigns", ["status"])
    op.create_table("campaign_segments", id_column(), tenant(), sa.Column("name", sa.String(120), nullable=False), sa.Column("filters", sa.JSON(), nullable=False))
    op.create_table("marketing_consents", id_column(), tenant(),
        sa.Column("contact_id", sa.Uuid(), sa.ForeignKey("crm_contacts.id", ondelete="CASCADE"), nullable=False),
        sa.Column("channel", sa.String(10), nullable=False), sa.Column("recipient", sa.String(320), nullable=False),
        sa.Column("granted", sa.Boolean(), nullable=False), sa.Column("evidence", sa.Text(), nullable=False),
        sa.Column("recorded_by", sa.Uuid(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("organization_id", "contact_id", "channel"))
    op.create_table("campaign_recipients", id_column(), tenant(),
        sa.Column("campaign_id", sa.Uuid(), sa.ForeignKey("campaigns.id", ondelete="CASCADE"), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("contact_id", sa.Uuid(), sa.ForeignKey("crm_contacts.id", ondelete="SET NULL")),
        sa.Column("recipient", sa.String(320), nullable=False), sa.Column("personalization", sa.JSON(), nullable=False),
        sa.Column("subject", sa.String(200), nullable=False), sa.Column("body", sa.Text(), nullable=False),
        sa.Column("message_id", sa.Uuid(), sa.ForeignKey("outbound_messages.id", ondelete="SET NULL"), unique=True),
        sa.Column("status", sa.String(30), nullable=False), sa.UniqueConstraint("campaign_id", "revision", "recipient"))
    op.create_table("campaign_approvals", id_column(), tenant(),
        sa.Column("campaign_id", sa.Uuid(), sa.ForeignKey("campaigns.id", ondelete="CASCADE"), nullable=False),
        sa.Column("decided_by", sa.Uuid(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("decision", sa.String(20), nullable=False), sa.Column("snapshot", sa.JSON(), nullable=False), created())
    op.create_table("campaign_audit", id_column(), tenant(),
        sa.Column("campaign_id", sa.Uuid(), sa.ForeignKey("campaigns.id", ondelete="SET NULL")),
        sa.Column("user_id", sa.Uuid(), sa.ForeignKey("users.id")), sa.Column("action", sa.String(60), nullable=False),
        sa.Column("detail", sa.JSON(), nullable=False), created())
    op.create_table("campaign_delivery_attempts", id_column(), tenant(),
        sa.Column("message_id", sa.Uuid(), sa.ForeignKey("outbound_messages.id", ondelete="CASCADE"), nullable=False),
        sa.Column("attempt", sa.Integer(), nullable=False), sa.Column("status", sa.String(30), nullable=False),
        sa.Column("provider_id", sa.String(200)), sa.Column("error", sa.Text()), created(), sa.UniqueConstraint("message_id", "attempt"))
    for table in ["campaign_segments", "marketing_consents", "campaign_recipients", "campaign_approvals", "campaign_audit", "campaign_delivery_attempts"]:
        op.create_index(f"ix_{table}_organization_id", table, ["organization_id"])
    for table in ["campaign_recipients", "campaign_approvals", "campaign_audit"]:
        op.create_index(f"ix_{table}_campaign_id", table, ["campaign_id"])


def downgrade():
    for table in ["campaign_delivery_attempts", "campaign_audit", "campaign_approvals", "campaign_recipients", "marketing_consents", "campaign_segments", "campaigns"]:
        op.drop_table(table)
