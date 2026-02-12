"""add tenant scope for master/override/generated tables

Revision ID: 20260211_0002
Revises: 20260211_0001
Create Date: 2026-02-11 00:30:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect
from sqlalchemy.exc import NoSuchTableError


# revision identifiers, used by Alembic.
revision: str = "20260211_0002"
down_revision: Union[str, Sequence[str], None] = "20260211_0001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _has_table(bind, table_name: str) -> bool:
    insp = inspect(bind)
    return table_name in insp.get_table_names()


def _has_column(bind, table_name: str, col_name: str) -> bool:
    insp = inspect(bind)
    try:
        return any(c["name"] == col_name for c in insp.get_columns(table_name))
    except NoSuchTableError:
        return False


def _is_column_nullable(bind, table_name: str, col_name: str) -> bool:
    insp = inspect(bind)
    try:
        for col in insp.get_columns(table_name):
            if col["name"] == col_name:
                return bool(col.get("nullable", True))
    except NoSuchTableError:
        return True
    return True


def _has_constraint(bind, table_name: str, constraint_name: str) -> bool:
    if not _has_table(bind, table_name):
        return False
    insp = inspect(bind)
    return any(c["name"] == constraint_name for c in insp.get_unique_constraints(table_name))


def _has_fk(bind, table_name: str, fk_name: str) -> bool:
    if not _has_table(bind, table_name):
        return False
    insp = inspect(bind)
    return any(fk.get("name") == fk_name for fk in insp.get_foreign_keys(table_name))


def _create_master_products_table() -> None:
    op.create_table(
        "master_products",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("tenant_id", sa.Integer(), nullable=False),
        sa.Column("brand", sa.Text(), nullable=False),
        sa.Column("reference", sa.Text(), nullable=False),
        sa.Column("price_jpy", sa.Text(), nullable=True),
        sa.Column("case_size_mm", sa.Text(), nullable=True),
        sa.Column("movement", sa.Text(), nullable=True),
        sa.Column("case_material", sa.Text(), nullable=True),
        sa.Column("bracelet_strap", sa.Text(), nullable=True),
        sa.Column("dial_color", sa.Text(), nullable=True),
        sa.Column("water_resistance_m", sa.Text(), nullable=True),
        sa.Column("buckle", sa.Text(), nullable=True),
        sa.Column("warranty_years", sa.Text(), nullable=True),
        sa.Column("collection", sa.Text(), nullable=True),
        sa.Column("movement_caliber", sa.Text(), nullable=True),
        sa.Column("case_thickness_mm", sa.Text(), nullable=True),
        sa.Column("lug_width_mm", sa.Text(), nullable=True),
        sa.Column("remarks", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["tenants.id"],
            name="fk_master_products_tenant_id",
            ondelete="RESTRICT",
        ),
        sa.UniqueConstraint(
            "tenant_id",
            "brand",
            "reference",
            name="uq_master_products_tenant_brand_reference",
        ),
    )


def _create_product_overrides_table() -> None:
    op.create_table(
        "product_overrides",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("tenant_id", sa.Integer(), nullable=False),
        sa.Column("brand", sa.Text(), nullable=False),
        sa.Column("reference", sa.Text(), nullable=False),
        sa.Column("price_jpy", sa.Text(), nullable=True),
        sa.Column("case_size_mm", sa.Text(), nullable=True),
        sa.Column("movement", sa.Text(), nullable=True),
        sa.Column("case_material", sa.Text(), nullable=True),
        sa.Column("bracelet_strap", sa.Text(), nullable=True),
        sa.Column("dial_color", sa.Text(), nullable=True),
        sa.Column("water_resistance_m", sa.Text(), nullable=True),
        sa.Column("buckle", sa.Text(), nullable=True),
        sa.Column("warranty_years", sa.Text(), nullable=True),
        sa.Column("collection", sa.Text(), nullable=True),
        sa.Column("movement_caliber", sa.Text(), nullable=True),
        sa.Column("case_thickness_mm", sa.Text(), nullable=True),
        sa.Column("lug_width_mm", sa.Text(), nullable=True),
        sa.Column("remarks", sa.Text(), nullable=True),
        sa.Column("editor_note", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["tenants.id"],
            name="fk_product_overrides_tenant_id",
            ondelete="RESTRICT",
        ),
        sa.UniqueConstraint(
            "tenant_id",
            "brand",
            "reference",
            name="uq_product_overrides_tenant_brand_reference",
        ),
    )


def _create_generated_articles_table() -> None:
    op.create_table(
        "generated_articles",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("tenant_id", sa.Integer(), nullable=False),
        sa.Column("brand", sa.Text(), nullable=False),
        sa.Column("reference", sa.Text(), nullable=False),
        sa.Column("payload_json", sa.Text(), nullable=False),
        sa.Column("intro_text", sa.Text(), nullable=True),
        sa.Column("specs_text", sa.Text(), nullable=True),
        sa.Column("rewrite_depth", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("rewrite_parent_id", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["tenants.id"],
            name="fk_generated_articles_tenant_id",
            ondelete="RESTRICT",
        ),
    )


def upgrade() -> None:
    bind = op.get_bind()

    if not _has_table(bind, "master_products"):
        _create_master_products_table()
    elif not _has_column(bind, "master_products", "tenant_id"):
        op.add_column("master_products", sa.Column("tenant_id", sa.Integer(), nullable=True))

    if not _has_table(bind, "product_overrides"):
        _create_product_overrides_table()
    elif not _has_column(bind, "product_overrides", "tenant_id"):
        op.add_column("product_overrides", sa.Column("tenant_id", sa.Integer(), nullable=True))

    if not _has_table(bind, "generated_articles"):
        _create_generated_articles_table()
    elif not _has_column(bind, "generated_articles", "tenant_id"):
        op.add_column("generated_articles", sa.Column("tenant_id", sa.Integer(), nullable=True))

    # Ensure a default tenant exists for backfill.
    bind.execute(sa.text("""
        INSERT INTO tenants (name, plan)
        SELECT 'Default', 'B'
        WHERE NOT EXISTS (SELECT 1 FROM tenants WHERE name = 'Default')
    """))
    default_tenant_id = bind.execute(
        sa.text("SELECT id FROM tenants WHERE name = 'Default' ORDER BY id ASC LIMIT 1")
    ).scalar_one()

    if _has_table(bind, "master_products") and _has_column(bind, "master_products", "tenant_id"):
        bind.execute(sa.text("UPDATE master_products SET tenant_id = :tid WHERE tenant_id IS NULL"), {"tid": default_tenant_id})
    if _has_table(bind, "product_overrides") and _has_column(bind, "product_overrides", "tenant_id"):
        bind.execute(sa.text("UPDATE product_overrides SET tenant_id = :tid WHERE tenant_id IS NULL"), {"tid": default_tenant_id})
    if _has_table(bind, "generated_articles") and _has_column(bind, "generated_articles", "tenant_id"):
        bind.execute(sa.text("UPDATE generated_articles SET tenant_id = :tid WHERE tenant_id IS NULL"), {"tid": default_tenant_id})

    # Drop old uniqueness that did not include tenant scope (constraint name may differ by env).
    insp = inspect(bind)

    def _drop_unique_on_brand_reference(table: str) -> None:
        for uc in insp.get_unique_constraints(table):
            cols = uc.get("column_names") or []
            name = uc.get("name")
            # Drop only old UNIQUE(brand, reference) without tenant_id
            if name and set(cols) == {"brand", "reference"}:
                op.drop_constraint(name, table, type_="unique")

    if _has_table(bind, "master_products"):
        _drop_unique_on_brand_reference("master_products")
    if _has_table(bind, "product_overrides"):
        _drop_unique_on_brand_reference("product_overrides")

    # Add foreign keys (idempotent).
    if _has_table(bind, "master_products") and _has_column(bind, "master_products", "tenant_id") and not _has_fk(bind, "master_products", "fk_master_products_tenant_id"):
        op.create_foreign_key(
            "fk_master_products_tenant_id",
            "master_products",
            "tenants",
            ["tenant_id"],
            ["id"],
            ondelete="RESTRICT",
        )
    if _has_table(bind, "product_overrides") and _has_column(bind, "product_overrides", "tenant_id") and not _has_fk(bind, "product_overrides", "fk_product_overrides_tenant_id"):
        op.create_foreign_key(
            "fk_product_overrides_tenant_id",
            "product_overrides",
            "tenants",
            ["tenant_id"],
            ["id"],
            ondelete="RESTRICT",
        )
    if _has_table(bind, "generated_articles") and _has_column(bind, "generated_articles", "tenant_id") and not _has_fk(bind, "generated_articles", "fk_generated_articles_tenant_id"):
        op.create_foreign_key(
            "fk_generated_articles_tenant_id",
            "generated_articles",
            "tenants",
            ["tenant_id"],
            ["id"],
            ondelete="RESTRICT",
        )

    if _has_table(bind, "master_products") and not _has_constraint(bind, "master_products", "uq_master_products_tenant_brand_reference"):
        op.create_unique_constraint(
            "uq_master_products_tenant_brand_reference",
            "master_products",
            ["tenant_id", "brand", "reference"],
        )
    if _has_table(bind, "product_overrides") and not _has_constraint(bind, "product_overrides", "uq_product_overrides_tenant_brand_reference"):
        op.create_unique_constraint(
            "uq_product_overrides_tenant_brand_reference",
            "product_overrides",
            ["tenant_id", "brand", "reference"],
        )

    if _has_table(bind, "master_products") and _has_column(bind, "master_products", "tenant_id") and _is_column_nullable(bind, "master_products", "tenant_id"):
        op.alter_column("master_products", "tenant_id", existing_type=sa.Integer(), nullable=False)
    if _has_table(bind, "product_overrides") and _has_column(bind, "product_overrides", "tenant_id") and _is_column_nullable(bind, "product_overrides", "tenant_id"):
        op.alter_column("product_overrides", "tenant_id", existing_type=sa.Integer(), nullable=False)
    if _has_table(bind, "generated_articles") and _has_column(bind, "generated_articles", "tenant_id") and _is_column_nullable(bind, "generated_articles", "tenant_id"):
        op.alter_column("generated_articles", "tenant_id", existing_type=sa.Integer(), nullable=False)

    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_master_products_tenant_brand_norm_reference_norm "
        "ON master_products (tenant_id, lower(trim(brand)), lower(trim(reference)))"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_generated_articles_tenant_created "
        "ON generated_articles (tenant_id, created_at)"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_generated_articles_tenant_created")
    op.execute("DROP INDEX IF EXISTS ix_master_products_tenant_brand_norm_reference_norm")

    op.drop_constraint("uq_product_overrides_tenant_brand_reference", "product_overrides", type_="unique")
    op.drop_constraint("uq_master_products_tenant_brand_reference", "master_products", type_="unique")

    op.drop_constraint("fk_generated_articles_tenant_id", "generated_articles", type_="foreignkey")
    op.drop_constraint("fk_product_overrides_tenant_id", "product_overrides", type_="foreignkey")
    op.drop_constraint("fk_master_products_tenant_id", "master_products", type_="foreignkey")

    op.alter_column("generated_articles", "tenant_id", existing_type=sa.Integer(), nullable=True)
    op.alter_column("product_overrides", "tenant_id", existing_type=sa.Integer(), nullable=True)
    op.alter_column("master_products", "tenant_id", existing_type=sa.Integer(), nullable=True)

    op.drop_column("generated_articles", "tenant_id")
    op.drop_column("product_overrides", "tenant_id")
    op.drop_column("master_products", "tenant_id")
