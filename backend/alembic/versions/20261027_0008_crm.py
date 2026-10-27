"""Create CRM records."""
import sqlalchemy as sa
from alembic import op

revision = "20261027_0008"
down_revision = "20261027_0007"
branch_labels = None
depends_on = None


def common():
    return [sa.Column("id", sa.Uuid(), primary_key=True),
            sa.Column("organization_id", sa.Uuid(), sa.ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False)]


def created():
    return sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now())


def upgrade():
    op.create_table("crm_companies", *common(), sa.Column("name", sa.String(200), nullable=False),
        sa.Column("normalized_name", sa.String(200), nullable=False), sa.Column("website", sa.String(500)), created(),
        sa.UniqueConstraint("organization_id", "normalized_name"))
    op.create_table("crm_contacts", *common(), sa.Column("company_id", sa.Uuid(), sa.ForeignKey("crm_companies.id", ondelete="SET NULL")),
        sa.Column("name", sa.String(200), nullable=False), sa.Column("email", sa.String(320)), sa.Column("phone", sa.String(40)), created(),
        sa.UniqueConstraint("organization_id", "email"))
    op.create_table("crm_leads", *common(), sa.Column("contact_id", sa.Uuid(), sa.ForeignKey("crm_contacts.id", ondelete="SET NULL")),
        sa.Column("company_id", sa.Uuid(), sa.ForeignKey("crm_companies.id", ondelete="SET NULL")),
        sa.Column("owner_id", sa.Uuid(), sa.ForeignKey("users.id", ondelete="SET NULL")),
        sa.Column("title", sa.String(200), nullable=False), sa.Column("stage", sa.String(30), nullable=False), created())
    op.create_table("crm_deals", *common(), sa.Column("lead_id", sa.Uuid(), sa.ForeignKey("crm_leads.id", ondelete="SET NULL")),
        sa.Column("owner_id", sa.Uuid(), sa.ForeignKey("users.id", ondelete="SET NULL")),
        sa.Column("title", sa.String(200), nullable=False), sa.Column("stage", sa.String(30), nullable=False),
        sa.Column("amount_minor", sa.Integer(), nullable=False), sa.Column("currency", sa.String(3), nullable=False), created())
    op.create_table("crm_activities", *common(), sa.Column("lead_id", sa.Uuid(), sa.ForeignKey("crm_leads.id", ondelete="CASCADE"), nullable=False),
        sa.Column("created_by", sa.Uuid(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("kind", sa.String(20), nullable=False), sa.Column("content", sa.Text(), nullable=False), created())
    for table in ("crm_companies", "crm_contacts", "crm_leads", "crm_deals", "crm_activities"):
        op.create_index(f"ix_{table}_organization_id", table, ["organization_id"])
    op.create_index("ix_crm_activities_lead_id", "crm_activities", ["lead_id"])


def downgrade():
    for table in ("crm_activities", "crm_deals", "crm_leads", "crm_contacts", "crm_companies"):
        op.drop_table(table)
