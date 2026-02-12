#!/usr/bin/env python3
import os
from typing import Optional

from psycopg import connect


def _postgres_url_from_env() -> str:
    raw = (os.getenv("DATABASE_URL") or "").strip()
    if not raw:
        raise RuntimeError("DATABASE_URL が未設定です")
    if raw.startswith("postgresql+psycopg://"):
        return raw.replace("postgresql+psycopg://", "postgresql://", 1)
    if not raw.startswith("postgresql://"):
        raise RuntimeError("DATABASE_URL は postgresql:// または postgresql+psycopg:// を指定してください")
    return raw


def _get_or_create_tenant(cur, name: str, plan: str) -> int:
    cur.execute("SELECT id FROM tenants WHERE name = %s ORDER BY id LIMIT 1", (name,))
    row = cur.fetchone()
    if row:
        return int(row[0])

    cur.execute(
        "INSERT INTO tenants (name, plan) VALUES (%s, %s) RETURNING id",
        (name, plan),
    )
    return int(cur.fetchone()[0])


def _upsert_user(cur, email: str, role: str, tenant_id: Optional[int]) -> None:
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
        (tenant_id, email, role),
    )


def main() -> None:
    db_url = _postgres_url_from_env()
    conn = connect(db_url)
    try:
        with conn.cursor() as cur:
            tenant_a_id = _get_or_create_tenant(cur, "Tenant A", "B")
            tenant_b_id = _get_or_create_tenant(cur, "Tenant B", "B")

            _upsert_user(cur, "platform-admin@example.com", "platform_admin", None)
            _upsert_user(cur, "staff-a@example.com", "tenant_staff", tenant_a_id)
            _upsert_user(cur, "staff-b@example.com", "tenant_staff", tenant_b_id)

        conn.commit()
    finally:
        conn.close()

    print("Seed completed:")
    print("- tenants: Tenant A, Tenant B")
    print("- users: platform-admin@example.com, staff-a@example.com, staff-b@example.com")


if __name__ == "__main__":
    main()
