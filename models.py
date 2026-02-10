import os
import sqlite3
import json
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "horologen.db")


# 必須CSVカラム
REQUIRED_CSV_COLUMNS = [
    'brand', 'reference', 'price_jpy', 'case_size_mm', 'movement',
    'case_material', 'bracelet_strap', 'dial_color', 'water_resistance_m',
    'buckle', 'warranty_years', 'collection', 'movement_caliber',
    'case_thickness_mm', 'lug_width_mm', 'remarks'
]

def init_db():
    """データベースを初期化"""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()

    # master_products テーブル
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS master_products (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            brand TEXT NOT NULL,
            reference TEXT NOT NULL,
            price_jpy TEXT,
            case_size_mm TEXT,
            movement TEXT,
            case_material TEXT,
            bracelet_strap TEXT,
            dial_color TEXT,
            water_resistance_m TEXT,
            buckle TEXT,
            warranty_years TEXT,
            collection TEXT,
            movement_caliber TEXT,
            case_thickness_mm TEXT,
            lug_width_mm TEXT,
            remarks TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(brand, reference)
        )
    ''')

    # product_overrides テーブル（editor_note 追加）
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS product_overrides (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            brand TEXT NOT NULL,
            reference TEXT NOT NULL,
            price_jpy TEXT,
            case_size_mm TEXT,
            movement TEXT,
            case_material TEXT,
            bracelet_strap TEXT,
            dial_color TEXT,
            water_resistance_m TEXT,
            buckle TEXT,
            warranty_years TEXT,
            collection TEXT,
            movement_caliber TEXT,
            case_thickness_mm TEXT,
            lug_width_mm TEXT,
            remarks TEXT,
            editor_note TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(brand, reference)
        )
    ''')

    # master_uploads テーブル（アップロード履歴）
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS master_uploads (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            filename TEXT NOT NULL,
            total_rows INTEGER,
            inserted_count INTEGER,
            updated_count INTEGER,
            error_count INTEGER,
            error_details TEXT,
            changed_count INTEGER DEFAULT 0,
            override_conflict_count INTEGER DEFAULT 0,
            sample_diffs TEXT,
            uploaded_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')

    # 既存テーブルへカラム追加（存在しない場合のみ）
    def _add_column_safe(table: str, coldef: str):
        try:
            cursor.execute(f'ALTER TABLE {table} ADD COLUMN {coldef}')
        except sqlite3.OperationalError:
            pass

    _add_column_safe('master_uploads', 'changed_count INTEGER DEFAULT 0')
    _add_column_safe('master_uploads', 'override_conflict_count INTEGER DEFAULT 0')
    _add_column_safe('master_uploads', 'sample_diffs TEXT')
    _add_column_safe('product_overrides', 'editor_note TEXT')
    _add_column_safe('generated_articles', 'rewrite_depth INTEGER DEFAULT 0')
    _add_column_safe('generated_articles', 'rewrite_parent_id INTEGER')

    # generated_articles テーブル（記事生成履歴）
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS generated_articles (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            brand TEXT NOT NULL,
            reference TEXT NOT NULL,
            payload_json TEXT NOT NULL,
            intro_text TEXT,
            specs_text TEXT,

            -- ★追加：言い換えガード用
            rewrite_depth INTEGER DEFAULT 0,
            rewrite_parent_id INTEGER,

            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    # monthly_generation_usage テーブル（月ごとの生成回数：サービス全体）
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS monthly_generation_usage (
            month_key TEXT PRIMARY KEY,      -- 例: "2026-02"
            used_count INTEGER DEFAULT 0,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)


    cursor.execute("""
        CREATE INDEX IF NOT EXISTS idx_generated_articles_brand_ref_created
        ON generated_articles (brand, reference, created_at DESC)
    """)
    cursor.execute("""
        CREATE INDEX IF NOT EXISTS idx_master_products_brand_reference
        ON master_products (brand, reference)
    """)

    conn.commit()
    conn.close()

def get_db_connection():
    """データベース接続を取得"""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def get_brands() -> list[str]:
    conn = sqlite3.connect(DB_PATH)
    try:
        rows = conn.execute(
            """
            SELECT DISTINCT LOWER(TRIM(brand)) AS brand
            FROM master_products
            WHERE brand IS NOT NULL
              AND TRIM(brand) <> ''
            ORDER BY brand ASC
            """
        ).fetchall()
        return [row[0] for row in rows if row and row[0] is not None]
    finally:
        conn.close()


def get_references_by_brand(brand: str) -> tuple[int, list[str]]:
    if not brand:
        return 0, []

    conn = sqlite3.connect(DB_PATH)
    try:
        item_rows = conn.execute(
            '''
            SELECT DISTINCT reference
            FROM master_products
            WHERE LOWER(TRIM(brand)) = LOWER(TRIM(?))
            ORDER BY reference ASC
            LIMIT 3000
            ''',
            (brand,)
        ).fetchall()
        count_row = conn.execute(
            '''
            SELECT COUNT(DISTINCT reference) AS ref_count
            FROM master_products
            WHERE LOWER(TRIM(brand)) = LOWER(TRIM(?))
            ''',
            (brand,)
        ).fetchone()

        items = [row[0] for row in item_rows if row and row[0] is not None]
        count = int(count_row[0]) if count_row else 0
        return count, items
    finally:
        conn.close()


def get_recent_generations(limit: int = 10) -> list[dict]:
    try:
        n = int(limit)
    except (TypeError, ValueError):
        n = 10
    n = max(1, min(n, 100))

    conn = get_db_connection()
    try:
        rows = conn.execute(
            """
            SELECT id, brand, reference, created_at, payload_json
            FROM generated_articles
            ORDER BY created_at DESC, id DESC
            LIMIT ?
            """,
            (n,)
        ).fetchall()
        out = []
        for row in rows:
            item = dict(row)
            created_at_raw = item.get("created_at")
            created_at_jst = created_at_raw
            try:
                dt = datetime.fromisoformat(created_at_raw) if created_at_raw else None
            except ValueError:
                dt = None
            if dt is None and created_at_raw:
                try:
                    dt = datetime.strptime(created_at_raw, "%Y-%m-%d %H:%M:%S")
                except ValueError:
                    dt = None
            if dt is not None:
                if dt.tzinfo is None:
                    dt = dt.replace(tzinfo=timezone.utc)
                created_at_jst = dt.astimezone(ZoneInfo("Asia/Tokyo")).strftime("%Y-%m-%d %H:%M:%S")
            item["created_at_jst"] = created_at_jst

            elapsed_ms = None
            payload_raw = item.get("payload_json")
            if payload_raw:
                try:
                    payload = json.loads(payload_raw)
                    v = payload.get("elapsed_ms")
                    if v is not None:
                        elapsed_ms = int(v)
                except (ValueError, TypeError, json.JSONDecodeError):
                    elapsed_ms = None
            item["elapsed_ms"] = elapsed_ms
            out.append(item)
        return out
    finally:
        conn.close()
