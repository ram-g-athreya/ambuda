"""add publication_location to proof_projects

Revision ID: d4e5f6a7b8c9
Revises: b3c4d5e6f7a8
Create Date: 2026-03-05 00:00:00.000000

"""

import sqlalchemy as sa
from alembic import op


# revision identifiers, used by Alembic.
revision = "d4e5f6a7b8c9"
down_revision = "b3c4d5e6f7a8"
branch_labels = None
depends_on = None


def _column_exists(conn, table, column):
    rows = conn.execute(sa.text(f"PRAGMA table_info({table})")).fetchall()
    return any(row[1] == column for row in rows)


def upgrade():
    conn = op.get_bind()
    if not _column_exists(conn, "proof_projects", "publication_location"):
        op.add_column(
            "proof_projects",
            sa.Column(
                "publication_location",
                sa.String(),
                nullable=False,
                server_default="",
            ),
        )


def downgrade():
    op.drop_column("proof_projects", "publication_location")
