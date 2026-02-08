"""Add author description

Revision ID: a3b1c4d5e6f7
Revises: 2f9e4536183c
Create Date: 2026-02-07 00:00:00.000000

"""

import sqlalchemy as sa
from alembic import op


# revision identifiers, used by Alembic.
revision = "a3b1c4d5e6f7"
down_revision = "2f9e4536183c"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("authors", sa.Column("description", sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column("authors", "description")
