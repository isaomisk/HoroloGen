#!/usr/bin/env python3
"""Create platform_admin safely for staging/prod via Render Shell."""

import os
import secrets
import string
import sys

from psycopg import connect
from werkzeug.security import generate_password_hash

EXIT_FAIL = 2


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


def _required_env(name: str) -> str:
    val = (os.getenv(name) or "").strip()
    if not val:
        raise RuntimeError(f"{name} が未設定です")
    return val


def _normalize_email(raw: str) -> str:
    return (raw or "").strip().lower()


def _generate_temp_password(length: int = 16) -> str:
    alphabet = string.ascii_letters + string.digits
    return "".join(secrets.choice(alphabet) for _ in range(length))


def main() -> int:
    db_url = _postgres_url_from_env()
    email = _normalize_email(_required_env("ADMIN_EMAIL"))
    admin_password = (os.getenv("ADMIN_PASSWORD") or "").strip()
    generated = False
    if not admin_password:
        admin_password = _generate_temp_password()
        generated = True

    conn = connect(db_url)
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT id FROM users WHERE lower(email) = %s LIMIT 1", (email,))
            existing = cur.fetchone()
            if existing is not None:
                print(f"exists: {email}")
                return 0

            password_hash = generate_password_hash(admin_password)
            cur.execute(
                """
                INSERT INTO users (tenant_id, email, role, is_active, password_hash, must_change_password, password_changed_at)
                VALUES (NULL, %s, 'platform_admin', true, %s, true, NULL)
                """,
                (email, password_hash),
            )
        conn.commit()
    finally:
        conn.close()

    print(f"created: {email}")
    if generated:
        print(f"temporary_password: {admin_password}")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except RuntimeError as e:
        print(f"[create_platform_admin] {e}", file=sys.stderr)
        raise SystemExit(EXIT_FAIL)
