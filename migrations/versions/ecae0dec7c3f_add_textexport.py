"""Add TextExport

Revision ID: ecae0dec7c3f
Revises: f0165b2bee3d
Create Date: 2025-12-21 09:05:29.303049

"""

import sqlalchemy as sa
from alembic import op


# revision identifiers, used by Alembic.
revision = "ecae0dec7c3f"
down_revision = "f0165b2bee3d"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "text_exports",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("text_id", sa.Integer(), nullable=False),
        sa.Column("slug", sa.String(), nullable=False),
        sa.Column("export_type", sa.String(), nullable=False),
        sa.Column("s3_path", sa.String(), nullable=False),
        sa.Column("size", sa.Integer(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(
            ["text_id"],
            ["texts.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("slug"),
    )


def downgrade() -> None:
    op.drop_table("text_exports")
