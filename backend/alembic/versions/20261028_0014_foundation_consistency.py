"""Align legacy identity constraints with ORM metadata without removing uniqueness."""

import sqlalchemy as sa

from alembic import op

revision = "20261028_0014"
down_revision = "20261028_0013"
branch_labels = None
depends_on = None

UNIQUE_COLUMNS = [
    ("users", "email"),
    ("organizations", "slug"),
    ("auth_sessions", "token_hash"),
    ("email_tokens", "token_hash"),
    ("invitations", "token_hash"),
]
TIMESTAMPS = [
    "users",
    "organizations",
    "memberships",
    "auth_sessions",
    "email_tokens",
    "invitations",
]


def upgrade():
    for table in TIMESTAMPS:
        op.execute(
            sa.text(f"UPDATE {table} SET created_at=CURRENT_TIMESTAMP WHERE created_at IS NULL")
        )
        op.alter_column(
            table, "created_at", existing_type=sa.DateTime(timezone=True), nullable=False
        )
    for table, column in UNIQUE_COLUMNS:
        # Keep the old unique constraint until the replacement unique index exists.
        op.drop_index(f"ix_{table}_{column}", table_name=table)
        op.create_index(f"ix_{table}_{column}", table, [column], unique=True)
        op.drop_constraint(f"{table}_{column}_key", table, type_="unique")
    # The existing unique organization index already enforces this constraint.
    op.drop_constraint("inbound_sites_organization_id_key", "inbound_sites", type_="unique")


def downgrade():
    op.create_unique_constraint(
        "inbound_sites_organization_id_key", "inbound_sites", ["organization_id"]
    )
    for table, column in UNIQUE_COLUMNS:
        op.create_unique_constraint(f"{table}_{column}_key", table, [column])
        op.drop_index(f"ix_{table}_{column}", table_name=table)
        op.create_index(f"ix_{table}_{column}", table, [column])
    for table in TIMESTAMPS:
        op.alter_column(
            table, "created_at", existing_type=sa.DateTime(timezone=True), nullable=True
        )
