"""add password auth fields to users

Revision ID: 20260213_0004
Revises: 20260213_0003
Create Date: 2026-02-13 12:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "20260213_0004"
down_revision: Union[str, Sequence[str], None] = "20260213_0003"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Keep upgrade safe for existing rows by using a temporary server default,
    # then remove the default so new rows must set password_hash explicitly.
    op.add_column(
        "users",
        sa.Column(
            "password_hash",
            sa.Text(),
            nullable=False,
            server_default=sa.text("'__unset_password__'"),
        ),
    )
    op.add_column(
        "users",
        sa.Column(
            "must_change_password",
            sa.Boolean(),
            nullable=False,
            server_default=sa.true(),
        ),
    )
    op.add_column(
        "users",
        sa.Column("password_changed_at", sa.DateTime(timezone=True), nullable=True),
    )
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        op.alter_column("users", "password_hash", server_default=None)


def downgrade() -> None:
    op.drop_column("users", "password_changed_at")
    op.drop_column("users", "must_change_password")
    op.drop_column("users", "password_hash")
