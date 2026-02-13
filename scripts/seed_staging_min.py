#!/usr/bin/env python3
import os
from psycopg import connect


def _postgres_url_from_env() -> str:
    raw = (os.getenv("DATABASE_URL") or "").strip()
    if not raw:
        raise RuntimeError("DATABASE_URL が未設定です")
    if raw.startswith("postgresql+psycopg://"):
        return raw.replace("postgresql+psycopg://", "postgresql://", 1)
    if raw.startswith("postgres://"):
        return "postgresql://" + raw[len("postgres://"):]
    if not raw.startswith("postgresql://"):
        raise RuntimeError("DATABASE_URL は postgres:// / postgresql:// / postgresql+psycopg:// のいずれかを指定してください")
    return raw


def _get_or_create_tenant(cur, name: str, plan: str) -> int:
    cur.execute("SELECT id FROM tenants WHERE name = %s ORDER BY id LIMIT 1", (name,))
    row = cur.fetchone()
    if row:
        return int(row[0])
    cur.execute("INSERT INTO tenants (name, plan) VALUES (%s, %s) RETURNING id", (name, plan))
    return int(cur.fetchone()[0])


def _upsert_staff_a(cur, tenant_id: int) -> None:
    cur.execute(
        """
        INSERT INTO users (tenant_id, email, role, is_active)
        VALUES (%s, %s, %s, true)
        ON CONFLICT (email)
        DO UPDATE SET
            tenant_id = EXCLUDED.tenant_id,
            role = EXCLUDED.role,
            is_active = EXCLUDED.is_active
        """,
        (tenant_id, "staff-a@example.com", "tenant_staff"),
    )


def _upsert_min_master(cur, tenant_id: int) -> str:
    cur.execute(
        """
        INSERT INTO master_products (
            tenant_id, brand, reference, price_jpy, updated_at
        )
        VALUES (%s, %s, %s, %s, CURRENT_TIMESTAMP)
        ON CONFLICT (tenant_id, brand, reference)
        DO UPDATE SET
            price_jpy = EXCLUDED.price_jpy,
            updated_at = CURRENT_TIMESTAMP
        RETURNING id
        """,
        (tenant_id, "TESTBRAND", "REF001", "123456"),
    )
    _ = cur.fetchone()
    return "upserted"


def main() -> None:
    db_url = _postgres_url_from_env()
    conn = connect(db_url)
    try:
        with conn.cursor() as cur:
            tenant_a_id = _get_or_create_tenant(cur, "Tenant A", "B")
            _upsert_staff_a(cur, tenant_a_id)
            master_state = _upsert_min_master(cur, tenant_a_id)
        conn.commit()
    finally:
        conn.close()

    print("seed_staging_min completed")
    print(f"- tenant: Tenant A (id={tenant_a_id})")
    print("- user: staff-a@example.com (tenant_staff)")
    print(f"- master_products: TESTBRAND / REF001 / price_jpy=123456 ({master_state})")


if __name__ == "__main__":
    main()
