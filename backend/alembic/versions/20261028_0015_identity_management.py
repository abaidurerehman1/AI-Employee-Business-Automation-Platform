"""Organization ownership, workspace membership activation and invitation revocation."""
import sqlalchemy as sa
from alembic import op

revision = "20261028_0015"
down_revision = "20261028_0014"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("organizations", sa.Column("owner_user_id", sa.Uuid(), nullable=True))
    op.create_foreign_key("fk_organizations_owner", "organizations", "users", ["owner_user_id"], ["id"])
    op.add_column("memberships", sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()))
    op.add_column("invitations", sa.Column("revoked_at", sa.DateTime(timezone=True)))
    op.execute("""UPDATE organizations AS o SET owner_user_id=(
        SELECT m.user_id FROM memberships m JOIN users u ON u.id=m.user_id
        WHERE m.organization_id=o.id AND m.role='admin' AND u.is_active=true
        ORDER BY m.created_at, m.id LIMIT 1)""")


def downgrade():
    op.drop_column("invitations", "revoked_at")
    op.drop_column("memberships", "is_active")
    op.drop_constraint("fk_organizations_owner", "organizations", type_="foreignkey")
    op.drop_column("organizations", "owner_user_id")
