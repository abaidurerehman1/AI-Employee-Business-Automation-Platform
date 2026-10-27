"""Expire visitor session credentials."""
from alembic import op
import sqlalchemy as sa

revision = "20261027_0010"
down_revision = "20261027_0009"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("visitor_conversations", sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()))
    op.alter_column("visitor_conversations", "expires_at", server_default=None)


def downgrade():
    op.drop_column("visitor_conversations", "expires_at")
