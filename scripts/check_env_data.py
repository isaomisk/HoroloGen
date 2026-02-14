#!/usr/bin/env python3
"""Environment-agnostic DB health/data check for staging/prod/dev.

This script intentionally requires DATABASE_URL to avoid checking the wrong DB.
"""

import argparse
import os
import sys

from psycopg import connect


def _postgres_url_from_env() -> str:
    raw = (os.getenv("DATABASE_URL") or "").strip()
    if not raw:
        raise RuntimeError(
            "DATABASE_URL が未設定です。Render Shell / ローカルシェルで DATABASE_URL を明示して実行してください。"
        )
    if raw.startswith("postgresql+psycopg://"):
        return raw.replace("postgresql+psycopg://", "postgresql://", 1)
    if raw.startswith("postgres://"):
        return "postgresql://" + raw[len("postgres://"):]
    if not raw.startswith("postgresql://"):
        raise RuntimeError("DATABASE_URL は postgres:// / postgresql:// / postgresql+psycopg:// のいずれかを指定してください")
    return raw


def _print_rows(title: str, cur, sql: str, params=()) -> None:
    print(f"\n[{title}]")
    cur.execute(sql, params)
    rows = cur.fetchall()
    if not rows:
        print("(no rows)")
        return
    for row in rows:
        print(row)


def run_checks() -> None:
    db_url = _postgres_url_from_env()
    conn = connect(db_url)
    try:
        with conn.cursor() as cur:
            _print_rows(
                "tenants",
                cur,
                "SELECT id, name, plan, created_at FROM tenants ORDER BY id",
            )
            _print_rows(
                "users (staff-a)",
                cur,
                """
                SELECT id, email, role, tenant_id, is_active, created_at
                FROM users
                WHERE email = %s
                ORDER BY id
                """,
                ("staff-a@example.com",),
            )
            _print_rows(
                "master_products count by tenant",
                cur,
                """
                SELECT tenant_id, COUNT(*) AS cnt
                FROM master_products
                GROUP BY tenant_id
                ORDER BY tenant_id
                """,
            )
            _print_rows(
                "master_products TESTBRAND/REF001",
                cur,
                """
                SELECT tenant_id, brand, reference, price_jpy, updated_at
                FROM master_products
                WHERE UPPER(TRIM(brand)) = 'TESTBRAND'
                  AND UPPER(TRIM(reference)) = 'REF001'
                ORDER BY tenant_id, brand
                """,
            )
            _print_rows(
                "product_overrides count by tenant",
                cur,
                """
                SELECT tenant_id, COUNT(*) AS cnt
                FROM product_overrides
                GROUP BY tenant_id
                ORDER BY tenant_id
                """,
            )
            _print_rows(
                "product_overrides TESTBRAND/REF001",
                cur,
                """
                SELECT tenant_id, brand, reference, price_jpy, editor_note, updated_at
                FROM product_overrides
                WHERE UPPER(TRIM(brand)) = 'TESTBRAND'
                  AND UPPER(TRIM(reference)) = 'REF001'
                ORDER BY tenant_id, brand
                """,
            )
    finally:
        conn.close()


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        description="staging/prod/dev 共通のデータ確認スクリプト（DATABASE_URL 必須）"
    )
    parser.parse_args(argv)
    run_checks()
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except RuntimeError as e:
        print(f"[check_env_data] {e}", file=sys.stderr)
        raise SystemExit(2)
