"""Add Page.uuid

Revision ID: 87f1671485a9
Revises: cedb1d7171ff
Create Date: 2026-01-17 09:31:28.222499

"""

import uuid
import sqlalchemy as sa
from alembic import op


# revision identifiers, used by Alembic.
revision = "87f1671485a9"
down_revision = "cedb1d7171ff"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("proof_pages", sa.Column("uuid", sa.String(), nullable=True))

    connection = op.get_bind()
    pages = connection.execute(sa.text("SELECT id FROM proof_pages WHERE uuid IS NULL"))
    for page in pages:
        connection.execute(
            sa.text("UPDATE proof_pages SET uuid = :uuid WHERE id = :id"),
            {"uuid": str(uuid.uuid4()), "id": page.id},
        )
    connection.commit()

    with op.batch_alter_table("proof_pages", schema=None) as batch_op:
        batch_op.alter_column("uuid", nullable=False)
        batch_op.create_unique_constraint("uq_proof_pages_uuid", ["uuid"])


def downgrade() -> None:
    with op.batch_alter_table("proof_pages", schema=None) as batch_op:
        batch_op.drop_constraint("uq_proof_pages_uuid", type_="unique")
        batch_op.drop_column("uuid")
