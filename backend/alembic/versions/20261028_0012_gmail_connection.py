"""Add encrypted Gmail connections."""
import sqlalchemy as sa
from alembic import op

revision = "20261028_0012"
down_revision = "20261028_0011"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table("gmail_connections", sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("organization_id", sa.Uuid(), sa.ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False),
        sa.Column("connected_by", sa.Uuid(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("email", sa.String(320), nullable=False), sa.Column("encrypted_refresh_token", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()))
    op.create_index("ix_gmail_connections_organization_id", "gmail_connections", ["organization_id"], unique=True)


def downgrade():
    op.drop_table("gmail_connections")
