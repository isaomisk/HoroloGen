#!/usr/bin/env python3
import os
import sqlite3
from typing import Iterable

from psycopg import connect


BATCH_SIZE_DEFAULT = 500


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


def _target_tenant_id_from_env() -> int:
    raw = (os.getenv("TENANT_ID") or "").strip()
    if not raw:
        raise RuntimeError("TENANT_ID が未設定です")
    try:
        tenant_id = int(raw)
    except ValueError as e:
        raise RuntimeError("TENANT_ID は整数で指定してください") from e
    if tenant_id <= 0:
        raise RuntimeError("TENANT_ID は 1 以上で指定してください")
    return tenant_id


def _sqlite_path_from_env() -> str:
    raw = (os.getenv("SQLITE_DB_PATH") or "").strip()
    if raw:
        return raw
    return os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "horologen.db")


def _normalize_brand(raw: str) -> str:
    return (raw or "").strip().upper()


def _normalize_reference(raw: str) -> str:
    return (raw or "").strip().upper()


def _read_sqlite_rows(sqlite_path: str) -> list[tuple]:
    conn = sqlite3.connect(sqlite_path)
    conn.row_factory = sqlite3.Row
    try:
        cur = conn.cursor()
        cur.execute(
            """
            SELECT
                brand, reference, price_jpy, case_size_mm, movement, case_material,
                bracelet_strap, dial_color, water_resistance_m, buckle, warranty_years,
                collection, movement_caliber, case_thickness_mm, lug_width_mm, remarks
            FROM master_products
            """
        )
        rows = cur.fetchall() or []
    finally:
        conn.close()

    out: list[tuple] = []
    for row in rows:
        brand = _normalize_brand(row["brand"])
        reference = _normalize_reference(row["reference"])
        if not brand or not reference:
            continue
        out.append(
            (
                brand,
                reference,
                row["price_jpy"],
                row["case_size_mm"],
                row["movement"],
                row["case_material"],
                row["bracelet_strap"],
                row["dial_color"],
                row["water_resistance_m"],
                row["buckle"],
                row["warranty_years"],
                row["collection"],
                row["movement_caliber"],
                row["case_thickness_mm"],
                row["lug_width_mm"],
                row["remarks"],
            )
        )
    return out


def _batched(rows: list[tuple], batch_size: int) -> Iterable[list[tuple]]:
    for i in range(0, len(rows), batch_size):
        yield rows[i : i + batch_size]


def main() -> None:
    pg_url = _postgres_url_from_env()
    tenant_id = _target_tenant_id_from_env()
    sqlite_path = _sqlite_path_from_env()
    batch_size = int((os.getenv("BATCH_SIZE") or str(BATCH_SIZE_DEFAULT)).strip())
    if batch_size < 1:
        batch_size = BATCH_SIZE_DEFAULT

    sqlite_rows = _read_sqlite_rows(sqlite_path)
    dedup: dict[tuple[str, str], tuple] = {}
    for row in sqlite_rows:
        dedup[(row[0], row[1])] = row
    rows = list(dedup.values())

    conn = connect(pg_url)
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT 1 FROM tenants WHERE id = %s", (tenant_id,))
            if cur.fetchone() is None:
                raise RuntimeError(f"指定 tenant_id={tenant_id} が tenants に存在しません")

            cur.execute("SELECT COUNT(*) FROM master_products WHERE tenant_id = %s", (tenant_id,))
            before_cnt = int(cur.fetchone()[0])

            insert_sql = """
                INSERT INTO master_products (
                    tenant_id, brand, reference, price_jpy, case_size_mm, movement, case_material,
                    bracelet_strap, dial_color, water_resistance_m, buckle, warranty_years,
                    collection, movement_caliber, case_thickness_mm, lug_width_mm, remarks, updated_at
                )
                VALUES (
                    %s, %s, %s, %s, %s, %s, %s,
                    %s, %s, %s, %s, %s,
                    %s, %s, %s, %s, %s, CURRENT_TIMESTAMP
                )
                ON CONFLICT (tenant_id, brand, reference) DO NOTHING
            """

            for batch in _batched(rows, batch_size):
                params = [(tenant_id, *r) for r in batch]
                cur.executemany(insert_sql, params)

            cur.execute("SELECT COUNT(*) FROM master_products WHERE tenant_id = %s", (tenant_id,))
            after_cnt = int(cur.fetchone()[0])

        conn.commit()
    finally:
        conn.close()

    inserted = max(0, after_cnt - before_cnt)
    skipped = max(0, len(rows) - inserted)
    print("import_master_products_from_sqlite completed")
    print(f"- tenant_id: {tenant_id}")
    print(f"- sqlite source rows (deduped): {len(rows)}")
    print(f"- inserted: {inserted}")
    print(f"- skipped(existing): {skipped}")


if __name__ == "__main__":
    main()
