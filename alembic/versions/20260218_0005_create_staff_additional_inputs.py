"""create staff_additional_inputs table

Revision ID: 20260218_0005
Revises: 20260213_0004
Create Date: 2026-02-18 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect


# revision identifiers, used by Alembic.
revision: str = "20260218_0005"
down_revision: Union[str, Sequence[str], None] = "20260213_0004"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _has_table(table_name: str) -> bool:
    bind = op.get_bind()
    insp = inspect(bind)
    return table_name in insp.get_table_names()


def upgrade() -> None:
    if not _has_table("staff_additional_inputs"):
        op.create_table(
            "staff_additional_inputs",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("tenant_id", sa.Integer(), nullable=False),
            sa.Column("brand", sa.Text(), nullable=False),
            sa.Column("reference", sa.Text(), nullable=False),
            sa.Column("content", sa.Text(), nullable=True),
            sa.Column("updated_by_user_id", sa.Integer(), nullable=True),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
            sa.ForeignKeyConstraint(
                ["tenant_id"],
                ["tenants.id"],
                name="fk_staff_additional_inputs_tenant_id",
                ondelete="RESTRICT",
            ),
            sa.UniqueConstraint(
                "tenant_id",
                "brand",
                "reference",
                name="uq_staff_additional_inputs_tenant_brand_reference",
            ),
        )

    op.execute(
        """
        INSERT INTO staff_additional_inputs (tenant_id, brand, reference, content, updated_at)
        SELECT tenant_id, brand, reference, editor_note, CURRENT_TIMESTAMP
        FROM product_overrides
        WHERE editor_note IS NOT NULL
          AND TRIM(editor_note) <> ''
        ON CONFLICT (tenant_id, brand, reference) DO UPDATE SET
            content = excluded.content,
            updated_at = CURRENT_TIMESTAMP
        """
    )


def downgrade() -> None:
    if _has_table("staff_additional_inputs"):
        op.drop_table("staff_additional_inputs")
