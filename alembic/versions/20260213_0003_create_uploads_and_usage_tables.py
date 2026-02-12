"""create master_uploads and monthly_generation_usage tables

Revision ID: 20260213_0003
Revises: 20260211_0002
Create Date: 2026-02-13 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect


# revision identifiers, used by Alembic.
revision: str = "20260213_0003"
down_revision: Union[str, Sequence[str], None] = "20260211_0002"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _has_table(table_name: str) -> bool:
    bind = op.get_bind()
    insp = inspect(bind)
    return table_name in insp.get_table_names()


def upgrade() -> None:
    if not _has_table("master_uploads"):
        op.create_table(
            "master_uploads",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("filename", sa.Text(), nullable=False),
            sa.Column("total_rows", sa.Integer(), nullable=True),
            sa.Column("inserted_count", sa.Integer(), nullable=True),
            sa.Column("updated_count", sa.Integer(), nullable=True),
            sa.Column("error_count", sa.Integer(), nullable=True),
            sa.Column("error_details", sa.Text(), nullable=True),
            sa.Column("changed_count", sa.Integer(), nullable=False, server_default=sa.text("0")),
            sa.Column("override_conflict_count", sa.Integer(), nullable=False, server_default=sa.text("0")),
            sa.Column("sample_diffs", sa.Text(), nullable=True),
            sa.Column("uploaded_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        )

    if not _has_table("monthly_generation_usage"):
        op.create_table(
            "monthly_generation_usage",
            sa.Column("month_key", sa.Text(), primary_key=True),
            sa.Column("used_count", sa.Integer(), nullable=False, server_default=sa.text("0")),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        )


def downgrade() -> None:
    if _has_table("monthly_generation_usage"):
        op.drop_table("monthly_generation_usage")
    if _has_table("master_uploads"):
        op.drop_table("master_uploads")
