"""Add text.genre_id

Revision ID: ec1a2265066c
Revises: 58389549f813
Create Date: 2025-11-23 11:20:27.743592

"""

import sqlalchemy as sa
from alembic import op


# revision identifiers, used by Alembic.
revision = "ec1a2265066c"
down_revision = "58389549f813"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("texts", sa.Column("genre_id", sa.Integer(), nullable=True))
    op.create_index(op.f("ix_texts_genre_id"), "texts", ["genre_id"], unique=False)
    with op.batch_alter_table("texts") as batch_op:
        batch_op.create_foreign_key("fk_texts_genre_id", "texts", ["genre_id"], ["id"])


def downgrade() -> None:
    with op.batch_alter_table("texts") as batch_op:
        batch_op.drop_constraint("fk_texts_genre_id", type_="foreignkey")
    op.drop_index(op.f("ix_texts_genre_id"), table_name="texts")
    op.drop_column("texts", "genre_id")
