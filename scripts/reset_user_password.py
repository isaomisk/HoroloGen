#!/usr/bin/env python3
"""Reset password safely for an existing user."""

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
    email = _normalize_email(_required_env("TARGET_EMAIL"))
    new_password = (os.getenv("NEW_PASSWORD") or "").strip()
    generated = False
    if not new_password:
        new_password = _generate_temp_password()
        generated = True

    conn = connect(db_url)
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT id FROM users WHERE lower(email) = %s LIMIT 1", (email,))
            row = cur.fetchone()
            if row is None:
                raise RuntimeError(f"target user not found: {email}")

            password_hash = generate_password_hash(new_password)
            cur.execute(
                """
                UPDATE users
                SET password_hash = %s,
                    must_change_password = true,
                    password_changed_at = NULL
                WHERE id = %s
                """,
                (password_hash, int(row[0])),
            )
        conn.commit()
    finally:
        conn.close()

    print(f"updated: {email}")
    if generated:
        print(f"temporary_password: {new_password}")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except RuntimeError as e:
        print(f"[reset_user_password] {e}", file=sys.stderr)
        raise SystemExit(EXIT_FAIL)
