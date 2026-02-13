import os
import sqlite3
import json
import hashlib
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Column,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    create_engine,
    func,
    text,
)
from sqlalchemy.orm import declarative_base, relationship, sessionmaker
from psycopg import connect as pg_connect
from psycopg.rows import dict_row

DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "horologen.db")
DEFAULT_DATABASE_URL = f"sqlite:///{DB_PATH}"


# ----------------------------
# SQLAlchemy (auth foundation)
# ----------------------------
def get_database_url() -> str:
    raw = os.getenv("DATABASE_URL", "").strip() or DEFAULT_DATABASE_URL
    if raw.startswith("postgres://"):
        raw = "postgresql://" + raw[len("postgres://"):]
    if raw.startswith("postgresql://"):
        raw = "postgresql+psycopg://" + raw[len("postgresql://"):]
    return raw


def _build_engine(url: str):
    connect_args = {"check_same_thread": False} if url.startswith("sqlite") else {}
    return create_engine(url, future=True, pool_pre_ping=True, connect_args=connect_args)


engine = _build_engine(get_database_url())
AuthSessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False, future=True)
Base = declarative_base()


class Tenant(Base):
    __tablename__ = "tenants"

    id = Column(Integer, primary_key=True)
    name = Column(String(255), nullable=False)
    plan = Column(String(1), nullable=False)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())

    __table_args__ = (
        CheckConstraint("plan IN ('A','B')", name="ck_tenants_plan"),
    )


class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True)
    tenant_id = Column(Integer, ForeignKey("tenants.id", ondelete="SET NULL"), nullable=True)
    email = Column(String(255), nullable=False, unique=True)
    role = Column(String(32), nullable=False)
    is_active = Column(Boolean, nullable=False, server_default=text("true"))
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())

    __table_args__ = (
        CheckConstraint("role IN ('platform_admin','tenant_staff')", name="ck_users_role"),
    )

    tenant = relationship("Tenant")


class LoginToken(Base):
    __tablename__ = "login_tokens"

    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    token_hash = Column(String(64), nullable=False, unique=True)
    expires_at = Column(DateTime(timezone=True), nullable=False)
    used_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    ip = Column(String(255), nullable=True)
    user_agent = Column(Text, nullable=True)

    user = relationship("User")


def get_auth_session():
    return AuthSessionLocal()


def now_utc() -> datetime:
    return datetime.now(timezone.utc)


def hash_token(raw_token: str, secret: str) -> str:
    # Pepper token with app secret to reduce reuse risk if DB hash leaks.
    payload = f"{secret}:{raw_token}".encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _sqlite_connect(row_factory: bool = False):
    conn = sqlite3.connect(DB_PATH)
    if row_factory:
        conn.row_factory = sqlite3.Row
    return conn


def _is_postgres_url(url: str) -> bool:
    return url.startswith("postgresql://") or url.startswith("postgresql+psycopg://")


def _convert_qmark_to_format(sql: str, n_params: int) -> str:
    if n_params <= 0:
        return sql
    out = []
    replaced = 0
    for ch in sql:
        if ch == "?" and replaced < n_params:
            out.append("%s")
            replaced += 1
        else:
            out.append(ch)
    if replaced != n_params:
        raise ValueError(f"placeholder mismatch: expected {n_params} '?', replaced {replaced}")
    return "".join(out)


class PostgresCursorCompat:
    def __init__(self, cursor):
        self._cursor = cursor
        self.lastrowid = None

    def execute(self, sql: str, params=()):
        if params is None:
            params = ()
        if isinstance(params, dict):
            raise TypeError("PostgresCursorCompat expects positional params (tuple/list), got dict")
        self._cursor.execute(_convert_qmark_to_format(sql, len(params)), params)
        return self

    def fetchone(self):
        return self._cursor.fetchone()

    def fetchall(self):
        return self._cursor.fetchall()


class PostgresConnCompat:
    def __init__(self, conn):
        self._conn = conn

    def cursor(self):
        return PostgresCursorCompat(self._conn.cursor(row_factory=dict_row))

    def execute(self, sql: str, params=()):
        cur = self.cursor()
        return cur.execute(sql, params)

    def commit(self):
        self._conn.commit()

    def rollback(self):
        self._conn.rollback()

    def close(self):
        self._conn.close()


# 必須CSVカラム
REQUIRED_CSV_COLUMNS = [
    'brand', 'reference', 'price_jpy', 'case_size_mm', 'movement',
    'case_material', 'bracelet_strap', 'dial_color', 'water_resistance_m',
    'buckle', 'warranty_years', 'collection', 'movement_caliber',
    'case_thickness_mm', 'lug_width_mm', 'remarks'
]

def init_db():
    """データベースを初期化"""
    if get_database_url().startswith("postgresql"):
        # PostgreSQL schema is managed via Alembic.
        return

    conn = _sqlite_connect()
    cursor = conn.cursor()

    # master_products テーブル
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS master_products (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            tenant_id INTEGER,
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
            UNIQUE(tenant_id, brand, reference)
        )
    ''')

    # product_overrides テーブル（editor_note 追加）
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS product_overrides (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            tenant_id INTEGER,
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
            UNIQUE(tenant_id, brand, reference)
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
    _add_column_safe('master_products', 'tenant_id INTEGER')
    _add_column_safe('product_overrides', 'tenant_id INTEGER')
    _add_column_safe('generated_articles', 'tenant_id INTEGER')

    # generated_articles テーブル（記事生成履歴）
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS generated_articles (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            tenant_id INTEGER,
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
    cursor.execute("""
        CREATE INDEX IF NOT EXISTS idx_generated_articles_tenant_created
        ON generated_articles (tenant_id, created_at DESC)
    """)
    cursor.execute("""
        CREATE INDEX IF NOT EXISTS idx_master_products_tenant_brand_reference
        ON master_products (tenant_id, brand, reference)
    """)

    conn.commit()
    conn.close()

def get_db_connection():
    """データベース接続を取得"""
    db_url = get_database_url()
    if _is_postgres_url(db_url):
        # psycopg expects postgresql:// scheme.
        pg_url = db_url.replace("postgresql+psycopg://", "postgresql://", 1)
        return PostgresConnCompat(pg_connect(pg_url))
    return _sqlite_connect(row_factory=True)


def _row_value(row, key: str, idx: int):
    if row is None:
        return None
    if isinstance(row, dict):
        return row.get(key)
    try:
        return row[key]
    except Exception:
        return row[idx]


def get_brands(tenant_id: int | None = None) -> list[str]:
    conn = get_db_connection()
    try:
        cur = conn.cursor()
        if tenant_id is None:
            cur.execute(
                """
                SELECT DISTINCT UPPER(TRIM(brand)) AS brand
                FROM master_products
                WHERE brand IS NOT NULL
                  AND TRIM(brand) <> ''
                ORDER BY brand ASC
                """
            )
        else:
            cur.execute(
                """
                SELECT DISTINCT UPPER(TRIM(brand)) AS brand
                FROM master_products
                WHERE tenant_id = ?
                  AND brand IS NOT NULL
                  AND TRIM(brand) <> ''
                ORDER BY brand ASC
                """,
                (tenant_id,),
            )
        rows = cur.fetchall() or []
        out = []
        for row in rows:
            value = _row_value(row, "brand", 0)
            if value is not None:
                out.append(value)
        return out
    finally:
        conn.close()


def get_references_by_brand(brand: str, tenant_id: int | None = None) -> tuple[int, list[str]]:
    if not brand:
        return 0, []

    conn = get_db_connection()
    try:
        cur = conn.cursor()
        if tenant_id is None:
            cur.execute(
                '''
                SELECT DISTINCT reference
                FROM master_products
                WHERE LOWER(TRIM(brand)) = LOWER(TRIM(?))
                ORDER BY reference ASC
                LIMIT 3000
                ''',
                (brand,)
            )
            item_rows = cur.fetchall() or []

            cur.execute(
                '''
                SELECT COUNT(DISTINCT reference) AS ref_count
                FROM master_products
                WHERE LOWER(TRIM(brand)) = LOWER(TRIM(?))
                ''',
                (brand,)
            )
            count_row = cur.fetchone()
        else:
            cur.execute(
                '''
                SELECT DISTINCT reference
                FROM master_products
                WHERE tenant_id = ?
                  AND LOWER(TRIM(brand)) = LOWER(TRIM(?))
                ORDER BY reference ASC
                LIMIT 3000
                ''',
                (tenant_id, brand)
            )
            item_rows = cur.fetchall() or []

            cur.execute(
                '''
                SELECT COUNT(DISTINCT reference) AS ref_count
                FROM master_products
                WHERE tenant_id = ?
                  AND LOWER(TRIM(brand)) = LOWER(TRIM(?))
                ''',
                (tenant_id, brand)
            )
            count_row = cur.fetchone()

        items = []
        for row in item_rows:
            value = _row_value(row, "reference", 0)
            if value is not None:
                items.append(value)
        count_raw = _row_value(count_row, "ref_count", 0)
        count = int(count_raw) if count_raw is not None else 0
        return count, items
    finally:
        conn.close()


def get_recent_generations(limit: int = 10, tenant_id: int | None = None) -> list[dict]:
    try:
        n = int(limit)
    except (TypeError, ValueError):
        n = 10
    n = max(1, min(n, 100))

    conn = get_db_connection()
    try:
        cur = conn.cursor()
        if tenant_id is None:
            cur.execute(
                """
                SELECT id, brand, reference, created_at, payload_json
                FROM generated_articles
                ORDER BY created_at DESC, id DESC
                LIMIT ?
                """,
                (n,)
            )
        else:
            cur.execute(
                """
                SELECT id, brand, reference, created_at, payload_json
                FROM generated_articles
                WHERE tenant_id = ?
                ORDER BY created_at DESC, id DESC
                LIMIT ?
                """,
                (tenant_id, n)
            )
        rows = cur.fetchall() or []
        out = []
        for row in rows:
            item = {
                "id": _row_value(row, "id", 0),
                "brand": _row_value(row, "brand", 1),
                "reference": _row_value(row, "reference", 2),
                "created_at": _row_value(row, "created_at", 3),
                "payload_json": _row_value(row, "payload_json", 4),
            }
            created_at_raw = item.get("created_at")
            created_at_jst = created_at_raw
            if isinstance(created_at_raw, datetime):
                dt = created_at_raw
            else:
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


def get_total_product_count(tenant_id: int | None = None) -> int:
    conn = get_db_connection()
    try:
        cur = conn.cursor()
        if tenant_id is None:
            cur.execute(
                """
                SELECT COUNT(*) AS cnt
                FROM master_products
                """
            )
        else:
            cur.execute(
                """
                SELECT COUNT(*) AS cnt
                FROM master_products
                WHERE tenant_id = ?
                """,
                (tenant_id,),
            )
        row = cur.fetchone()
        cnt = _row_value(row, "cnt", 0)
        return int(cnt) if cnt is not None else 0
    finally:
        conn.close()


def get_brand_summary_rows(month_start_iso: str, month_end_iso: str, tenant_id: int | None = None) -> list[dict]:
    conn = get_db_connection()
    use_postgres = _is_postgres_url(get_database_url())
    try:
        if tenant_id is None:
            brand_rows = conn.execute(
                """
                SELECT DISTINCT LOWER(TRIM(brand)) AS brand
                FROM master_products
                WHERE brand IS NOT NULL
                  AND TRIM(brand) <> ''
                ORDER BY brand ASC
                """
            ).fetchall()
        else:
            brand_rows = conn.execute(
                """
                SELECT DISTINCT LOWER(TRIM(brand)) AS brand
                FROM master_products
                WHERE tenant_id = ?
                  AND brand IS NOT NULL
                  AND TRIM(brand) <> ''
                ORDER BY brand ASC
                """,
                (tenant_id,),
            ).fetchall()

        brands = []
        for r in brand_rows or []:
            v = _row_value(r, "brand", 0)
            if v is not None:
                brands.append(v)

        if tenant_id is None:
            product_rows = conn.execute(
                """
                SELECT LOWER(TRIM(brand)) AS brand_norm, COUNT(DISTINCT reference) AS product_count
                FROM master_products
                WHERE brand IS NOT NULL
                  AND TRIM(brand) <> ''
                  AND reference IS NOT NULL
                  AND TRIM(reference) <> ''
                GROUP BY LOWER(TRIM(brand))
                """
            ).fetchall()
        else:
            product_rows = conn.execute(
                """
                SELECT LOWER(TRIM(brand)) AS brand_norm, COUNT(DISTINCT reference) AS product_count
                FROM master_products
                WHERE tenant_id = ?
                  AND brand IS NOT NULL
                  AND TRIM(brand) <> ''
                  AND reference IS NOT NULL
                  AND TRIM(reference) <> ''
                GROUP BY LOWER(TRIM(brand))
                """,
                (tenant_id,),
            ).fetchall()
        product_counts = {
            _row_value(row, "brand_norm", 0): int((_row_value(row, "product_count", 1) or 0))
            for row in product_rows
            if _row_value(row, "brand_norm", 0) is not None
        }

        if tenant_id is None and not use_postgres:
            monthly_rows = conn.execute(
                """
                SELECT LOWER(TRIM(brand)) AS brand_norm, COUNT(*) AS monthly_count
                FROM generated_articles
                WHERE brand IS NOT NULL
                  AND TRIM(brand) <> ''
                  AND datetime(created_at, '+9 hours') >= ?
                  AND datetime(created_at, '+9 hours') < ?
                GROUP BY LOWER(TRIM(brand))
                """,
                (month_start_iso, month_end_iso),
            ).fetchall()
        elif tenant_id is None and use_postgres:
            monthly_rows = conn.execute(
                """
                SELECT LOWER(TRIM(brand)) AS brand_norm, COUNT(*) AS monthly_count
                FROM generated_articles
                WHERE brand IS NOT NULL
                  AND TRIM(brand) <> ''
                  AND (created_at + INTERVAL '9 hour') >= ?
                  AND (created_at + INTERVAL '9 hour') < ?
                GROUP BY LOWER(TRIM(brand))
                """,
                (month_start_iso, month_end_iso),
            ).fetchall()
        elif not use_postgres:
            monthly_rows = conn.execute(
                """
                SELECT LOWER(TRIM(brand)) AS brand_norm, COUNT(*) AS monthly_count
                FROM generated_articles
                WHERE tenant_id = ?
                  AND brand IS NOT NULL
                  AND TRIM(brand) <> ''
                  AND datetime(created_at, '+9 hours') >= ?
                  AND datetime(created_at, '+9 hours') < ?
                GROUP BY LOWER(TRIM(brand))
                """,
                (tenant_id, month_start_iso, month_end_iso),
            ).fetchall()
        else:
            monthly_rows = conn.execute(
                """
                SELECT LOWER(TRIM(brand)) AS brand_norm, COUNT(*) AS monthly_count
                FROM generated_articles
                WHERE tenant_id = ?
                  AND brand IS NOT NULL
                  AND TRIM(brand) <> ''
                  AND (created_at + INTERVAL '9 hour') >= ?
                  AND (created_at + INTERVAL '9 hour') < ?
                GROUP BY LOWER(TRIM(brand))
                """,
                (tenant_id, month_start_iso, month_end_iso),
            ).fetchall()
        monthly_generations = {
            _row_value(row, "brand_norm", 0): int((_row_value(row, "monthly_count", 1) or 0))
            for row in monthly_rows
            if _row_value(row, "brand_norm", 0) is not None
        }

        if tenant_id is None:
            latest_rows = conn.execute(
                """
                SELECT brand_norm, reference
                FROM (
                    SELECT
                        LOWER(TRIM(brand)) AS brand_norm,
                        reference,
                        ROW_NUMBER() OVER (
                            PARTITION BY LOWER(TRIM(brand))
                            ORDER BY created_at DESC, id DESC
                        ) AS rn
                    FROM generated_articles
                    WHERE brand IS NOT NULL
                      AND TRIM(brand) <> ''
                )
                WHERE rn = 1
                """
            ).fetchall()
        else:
            latest_rows = conn.execute(
                """
                SELECT brand_norm, reference
                FROM (
                    SELECT
                        LOWER(TRIM(brand)) AS brand_norm,
                        reference,
                        ROW_NUMBER() OVER (
                            PARTITION BY LOWER(TRIM(brand))
                            ORDER BY created_at DESC, id DESC
                        ) AS rn
                    FROM generated_articles
                    WHERE tenant_id = ?
                      AND brand IS NOT NULL
                      AND TRIM(brand) <> ''
                )
                WHERE rn = 1
                """,
                (tenant_id,),
            ).fetchall()
        latest_references = {
            _row_value(row, "brand_norm", 0): (_row_value(row, "reference", 1) or "")
            for row in latest_rows
            if _row_value(row, "brand_norm", 0) is not None
        }

        rows = []
        for brand in brands:
            rows.append({
                "brand": brand,
                "product_count": product_counts.get(brand, 0),
                "monthly_generations": monthly_generations.get(brand, 0),
                "latest_reference": latest_references.get(brand, ""),
            })
        return rows
    finally:
        conn.close()
