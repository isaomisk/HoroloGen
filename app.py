from flask import Flask, render_template, request, redirect, url_for, flash, jsonify, session, abort
import json
import csv
import io
import os
import logging
import re
import logging
import binascii
import sqlite3
import time
import secrets
from datetime import datetime, timedelta
from functools import wraps

from sqlalchemy import select, text
from werkzeug.security import check_password_hash, generate_password_hash

from models import (
    init_db,
    get_db_connection,
    REQUIRED_CSV_COLUMNS,
    get_references_by_brand,
    get_brands,
    get_recent_generations,
    get_total_product_count,
    get_brand_summary_rows,
    get_auth_session,
    get_database_url,
    hash_token,
    now_utc,
    Tenant,
    User,
    LoginToken,
)
import llm_client as llmc
from url_discovery import discover_reference_urls
from errors import make_error_id, to_user_message, log_exception

# ----------------------------
# Plan / quota settings
# ----------------------------
PLAN_MODE = os.getenv("HOROLOGEN_PLAN", "limited").strip().lower()  # "limited" / "unlimited"
MONTHLY_LIMIT = int(os.getenv("HOROLOGEN_MONTHLY_LIMIT", "30"))

# ----------------------------
# Flask
# ----------------------------
if not logging.getLogger().handlers:
    logging.basicConfig(level=logging.INFO)

logger = logging.getLogger(__name__)
app = Flask(__name__)
init_db()
_boot_env_raw = (os.getenv("APP_ENV") or os.getenv("FLASK_ENV") or "").strip().lower()
if _boot_env_raw in {"development", "dev"}:
    _boot_env = "dev"
elif _boot_env_raw in {"production", "prod"}:
    _boot_env = "prod"
elif _boot_env_raw == "staging":
    _boot_env = "staging"
else:
    _boot_env = ""

_configured_secret_key = (
    (os.getenv("SECRET_KEY") or "").strip()
    or (os.getenv("HOROLOGEN_SECRET_KEY") or "").strip()
    or (os.getenv("FLASK_SECRET_KEY") or "").strip()
)
if _boot_env != "dev" and not _configured_secret_key:
    raise RuntimeError("SECRET_KEY is required in staging/prod")
app.secret_key = _configured_secret_key or binascii.hexlify(os.urandom(32)).decode("ascii")
app.config['UPLOAD_FOLDER'] = 'uploads'
app.config['MAX_CONTENT_LENGTH'] = 16 * 1024 * 1024  # 16MB max
os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)

BRANDS = ['cartier', 'omega', 'grand_seiko', 'iwc', 'panerai']
TENANT_STAFF_LIMIT = 5
MAGIC_LINK_TTL_MINUTES = 15
AUTH_REQUEST_MESSAGE = "該当アカウントが存在する場合、ログインURLを送信しました。"


def _flash_error_from_exception(e: Exception, context=None, category: str = "error") -> str:
    error_id = make_error_id()
    log_exception(app.logger, e, error_id, context or {})
    flash(to_user_message(e, error_id), category)
    return error_id


def _flash_error_from_hint(hint: str, context=None, category: str = "error") -> str:
    error_id = make_error_id()
    app.logger.error("error_id=%s context=%s hint=%s", error_id, context or {}, hint)
    flash(to_user_message(RuntimeError(hint), error_id), category)
    return error_id


def _normalize_email(raw: str) -> str:
    return (raw or "").strip().lower()


def _app_env() -> str:
    raw = (os.getenv("APP_ENV") or os.getenv("FLASK_ENV") or "").strip().lower()
    if raw in {"production", "prod"}:
        return "prod"
    if raw in {"development", "dev"}:
        return "dev"
    if raw == "staging":
        return "staging"
    return ""


def _is_auth_request_enabled() -> bool:
    env = _app_env()
    if env != "dev":
        return False
    return (os.getenv("DEBUG_AUTH_LINKS", "") or "").strip() == "1"


def normalize_brand(raw: str) -> str:
    return (raw or "").strip().upper()


def normalize_reference(raw: str) -> str:
    return (raw or "").strip().upper()


def _generate_temporary_password(length: int = 14) -> str:
    alphabet = "ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz23456789"
    return "".join(secrets.choice(alphabet) for _ in range(length))


def _count_master_products_for_reference(tenant_id: int, brand: str, reference: str) -> int | None:
    if not brand or not reference:
        return None
    conn = get_db_connection()
    try:
        row = conn.execute(
            """
            SELECT COUNT(*) AS c
            FROM master_products
            WHERE tenant_id = ? AND brand = ? AND reference = ?
            """,
            (tenant_id, brand, reference),
        ).fetchone()
        return int(row["c"] if row else 0)
    finally:
        try:
            conn.close()
        except Exception:
            pass


def _save_staff_additional_input(
    conn,
    tenant_id: int,
    brand: str,
    reference: str,
    content: str,
    updated_by_user_id: int | None = None,
) -> None:
    clean_content = (content or "").strip()
    conn.execute(
        """
        INSERT INTO staff_additional_inputs
        (tenant_id, brand, reference, content, updated_by_user_id, updated_at)
        VALUES (?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
        ON CONFLICT(tenant_id, brand, reference) DO UPDATE SET
            content = excluded.content,
            updated_by_user_id = excluded.updated_by_user_id,
            updated_at = CURRENT_TIMESTAMP
        """,
        (tenant_id, brand, reference, clean_content, updated_by_user_id),
    )


def _build_client_ip() -> str:
    forwarded_for = request.headers.get("X-Forwarded-For", "")
    if forwarded_for:
        return forwarded_for.split(",")[0].strip()
    return request.remote_addr or ""


def login_required(view_func):
    @wraps(view_func)
    def wrapped(*args, **kwargs):
        if not session.get("user_id"):
            return redirect(url_for("auth_login", next=request.path))
        if session.get("must_change_password") and request.endpoint not in {"auth_change_password", "auth_logout", "static"}:
            return redirect(url_for("auth_change_password"))
        return view_func(*args, **kwargs)
    return wrapped


def require_admin(view_func):
    @wraps(view_func)
    def wrapped(*args, **kwargs):
        if not session.get("user_id"):
            return redirect(url_for("auth_login", next=request.path))
        if (session.get("user_role") or "") != "platform_admin":
            abort(403)
        return view_func(*args, **kwargs)
    return wrapped


def _safe_int(raw) -> int | None:
    if raw is None:
        return None
    try:
        return int(raw)
    except (TypeError, ValueError):
        return None


def _is_platform_admin() -> bool:
    return (session.get("user_role") or "") == "platform_admin"


def _tenant_exists(tenant_id: int) -> bool:
    db = get_auth_session()
    try:
        row = db.execute(select(Tenant.id).where(Tenant.id == tenant_id)).scalar_one_or_none()
        return row is not None
    except Exception:
        app.logger.exception("failed to validate tenant_id=%s", tenant_id)
        return False
    finally:
        db.close()


def _resolve_staff_tenant_id() -> tuple[int | None, str | None]:
    role = (session.get("user_role") or "").strip()

    if role == "tenant_staff":
        tenant_id = _get_current_tenant_id()
        if tenant_id is None:
            return None, "tenant_required"
        return tenant_id, None

    if role == "platform_admin":
        raw_arg = request.args.get("tenant_id")
        if raw_arg is not None:
            raw_arg = raw_arg.strip()
            if raw_arg == "":
                session.pop("impersonate_tenant_id", None)
            else:
                tenant_id_from_query = _safe_int(raw_arg)
                if tenant_id_from_query is None or not _tenant_exists(tenant_id_from_query):
                    return None, "tenant_invalid"
                session["impersonate_tenant_id"] = tenant_id_from_query

        impersonate_tenant_id = _safe_int(session.get("impersonate_tenant_id"))
        if impersonate_tenant_id is None:
            return None, "tenant_required"
        if not _tenant_exists(impersonate_tenant_id):
            session.pop("impersonate_tenant_id", None)
            return None, "tenant_required"
        return impersonate_tenant_id, None

    return None, "forbidden"


@app.context_processor
def inject_auth_context():
    is_authenticated = bool(session.get("user_id"))
    is_admin = is_authenticated and _is_platform_admin()
    staff_tenant_id = _safe_int(session.get("impersonate_tenant_id")) if is_admin else _get_current_tenant_id()

    tenant_options = []
    if is_admin:
        try:
            tenant_options = _load_tenant_options()
        except Exception:
            app.logger.exception("failed to load tenant options for nav")

    return {
        "is_authenticated": is_authenticated,
        "current_user_email": session.get("user_email", ""),
        "current_user_role": session.get("user_role", ""),
        "is_admin": is_admin,
        "can_access_admin": is_admin,
        "staff_tenant_id": staff_tenant_id,
        "admin_tenant_options": tenant_options,
    }


def _get_current_tenant_id() -> int | None:
    raw = session.get("tenant_id")
    if raw is None:
        return None
    try:
        return int(raw)
    except (TypeError, ValueError):
        return None


def _staff_tenant_or_redirect():
    tenant_id, err = _resolve_staff_tenant_id()
    if tenant_id is not None:
        return tenant_id, None

    if err == "tenant_invalid":
        flash("指定されたテナントは存在しません。", "warning")
    elif err == "tenant_required":
        if _is_platform_admin():
            flash("テナントを選択してください。", "warning")
            return None, redirect(url_for("staff_search"))
        flash("テナント未所属のため staff 機能を利用できません。", "warning")
    else:
        flash("staff 権限がありません。", "warning")
    return None, redirect(url_for("auth_login"))


def _safe_next_path(raw: str) -> str:
    val = (raw or "").strip()
    if not val.startswith("/"):
        return ""
    if val.startswith("//"):
        return ""
    return val


def _staff_tenant_or_403_json():
    tenant_id, err = _resolve_staff_tenant_id()
    if tenant_id is not None:
        return tenant_id, None
    if err in ("tenant_required", "tenant_invalid"):
        return None, (jsonify({"error": "tenant_required"}), 403)
    return None, (jsonify({"error": "forbidden"}), 403)


def _load_tenant_options() -> list[Tenant]:
    db = get_auth_session()
    try:
        return list(db.execute(select(Tenant).order_by(Tenant.name.asc(), Tenant.id.asc())).scalars())
    finally:
        db.close()


def _load_resettable_staff_users() -> list[User]:
    db = get_auth_session()
    try:
        return list(
            db.execute(
                select(User)
                .where(User.role == "tenant_staff")
                .order_by(User.tenant_id.asc(), User.email.asc())
            ).scalars()
        )
    finally:
        db.close()


def _count_active_tenant_staff(db, tenant_id: int) -> int:
    return int(
        db.execute(
            text(
                """
                SELECT COUNT(*)
                FROM users
                WHERE tenant_id = :tenant_id
                  AND role = 'tenant_staff'
                  AND is_active = true
                """
            ),
            {"tenant_id": tenant_id},
        ).scalar_one()
    )


def _count_active_platform_admins(db) -> int:
    return int(
        db.execute(
            text(
                """
                SELECT COUNT(*)
                FROM users
                WHERE role = 'platform_admin'
                  AND is_active = true
                """
            )
        ).scalar_one()
    )


def _parse_sort_params(
    raw_sort: str | None,
    raw_dir: str | None,
    allowed_sorts: set[str],
    default_sort: str,
    default_dir: str,
) -> tuple[str, str]:
    sort = (raw_sort or "").strip().lower()
    if sort not in allowed_sorts:
        sort = default_sort
    direction = (raw_dir or "").strip().lower()
    if direction not in {"asc", "desc"}:
        direction = default_dir
    return sort, direction


# ----------------------------
# Quota helpers (service-wide monthly limit)
# ----------------------------
def _month_key_jst() -> str:
    dt = datetime.utcnow() + timedelta(hours=9)
    return dt.strftime("%Y-%m")

def get_monthly_usage(conn) -> int:
    mk = _month_key_jst()
    row = conn.execute(
        "SELECT used_count FROM monthly_generation_usage WHERE month_key = ?",
        (mk,)
    ).fetchone()
    return int(row["used_count"]) if row else 0

def remaining_quota(conn) -> int:
    if PLAN_MODE == "unlimited":
        return 10**9  # display only
    used = get_monthly_usage(conn)
    return max(0, MONTHLY_LIMIT - used)

def consume_quota_or_block(n: int = 1) -> tuple[bool, str]:
    """
    called right before LLM call.
    limited: if exceeded => block. if OK => increment used_count (+n)
    unlimited: always OK
    """
    if PLAN_MODE == "unlimited":
        return True, ""

    conn = get_db_connection()
    try:
        if get_database_url().startswith("postgresql"):
            conn.execute("BEGIN")
        else:
            conn.execute("BEGIN IMMEDIATE")
        mk = _month_key_jst()

        row = conn.execute(
            "SELECT used_count FROM monthly_generation_usage WHERE month_key = ?",
            (mk,)
        ).fetchone()
        used = int(row["used_count"]) if row else 0

        if used + n > MONTHLY_LIMIT:
            conn.rollback()
            return False, "quota exceeded"

        if row:
            conn.execute(
                "UPDATE monthly_generation_usage "
                "SET used_count = used_count + ?, updated_at = CURRENT_TIMESTAMP "
                "WHERE month_key = ?",
                (n, mk)
            )
        else:
            conn.execute(
                "INSERT INTO monthly_generation_usage (month_key, used_count) VALUES (?, ?)",
                (mk, n)
            )

        conn.commit()
        return True, ""
    except Exception as e:
        try:
            conn.rollback()
        except Exception:
            pass
        error_id = make_error_id()
        log_exception(app.logger, e, error_id, {"scope": "quota", "action": "consume_quota_or_block"})
        return False, "db locked" if "locked" in (str(e).lower()) else "unknown"
    finally:
        try:
            conn.close()
        except Exception:
            pass

def get_quota_view() -> tuple[str, int, int]:
    conn = get_db_connection()
    try:
        mk = _month_key_jst()
        used = get_monthly_usage(conn)
        rem = remaining_quota(conn)
        return mk, used, rem
    finally:
        try:
            conn.close()
        except Exception:
            pass


def _month_range_jst_from_key(month_key: str) -> tuple[str, str]:
    base = datetime.strptime(month_key, "%Y-%m")
    if base.month == 12:
        next_month = datetime(base.year + 1, 1, 1)
    else:
        next_month = datetime(base.year, base.month + 1, 1)
    start = base.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    end = next_month.replace(hour=0, minute=0, second=0, microsecond=0)
    return start.strftime("%Y-%m-%d %H:%M:%S"), end.strftime("%Y-%m-%d %H:%M:%S")


def get_brand_summary_view(month_key: str, tenant_id: int | None = None) -> tuple[int, list[dict]]:
    start_iso, end_iso = _month_range_jst_from_key(month_key)
    total = get_total_product_count(tenant_id=tenant_id)
    rows = get_brand_summary_rows(start_iso, end_iso, tenant_id=tenant_id)
    return total, rows


# ----------------------------
# History view helper
# ----------------------------
def _build_history_rows(rows):
    out = []
    for r in rows:
        payload = {}
        try:
            payload = json.loads(r['payload_json']) if r['payload_json'] else {}
        except Exception:
            payload = {}

        created_raw = r["created_at"]  # SQLite UTC
        created_jst = created_raw
        try:
            dt = datetime.strptime(created_raw, "%Y-%m-%d %H:%M:%S")
            created_jst = (dt + timedelta(hours=9)).strftime("%Y-%m-%d %H:%M:%S")
        except Exception:
            pass

        # Prefer DB columns if present, fallback to payload (for old records)
        db_depth = None
        db_parent = None
        try:
            db_depth = r["rewrite_depth"]
            db_parent = r["rewrite_parent_id"]
        except Exception:
            pass

        depth = int(db_depth) if db_depth is not None else int(payload.get("rewrite_depth", 0) or 0)
        parent_id = db_parent if db_parent is not None else payload.get("rewrite_parent_id", None)

        out.append({
            "id": r["id"],
            "created_at": created_jst,
            "intro_text": r["intro_text"] or "",
            "specs_text": r["specs_text"] or "",
            "selected_reference_url": payload.get("selected_reference_url", "") or payload.get("reference_url", "") or "",
            "selected_reference_reason": payload.get("selected_reference_reason", "") or "",
            "similarity_percent": payload.get("similarity_percent", 0) or 0,
            "similarity_level": payload.get("similarity_level", "blue") or "blue",
            "rewrite_applied": bool(payload.get("rewrite_applied", False)),

            "rewrite_depth": depth,
            "rewrite_parent_id": parent_id,
        })
    return out


# ----------------------------
# Routes
# ----------------------------
@app.route('/auth/request', methods=['GET', 'POST'])
def auth_request():
    env = _app_env()
    if env != "dev":
        return render_template("auth_request_disabled.html"), 404

    if not _is_auth_request_enabled():
        return render_template("auth_request_disabled.html"), 404

    issued_verify_url = ""
    if request.method == 'POST':
        email = _normalize_email(request.form.get('email', ''))
        if email:
            db = get_auth_session()
            try:
                user = db.execute(
                    select(User).where(
                        User.email == email,
                        User.is_active.is_(True),
                    )
                ).scalar_one_or_none()

                if user:
                    raw_token = secrets.token_urlsafe(32)
                    token = LoginToken(
                        user_id=user.id,
                        token_hash=hash_token(raw_token, app.secret_key),
                        expires_at=now_utc() + timedelta(minutes=MAGIC_LINK_TTL_MINUTES),
                        ip=_build_client_ip()[:255],
                        user_agent=(request.user_agent.string or "")[:1000],
                    )
                    db.add(token)
                    db.commit()
                    issued_verify_url = url_for('auth_verify', token=raw_token, _external=True)
            except Exception as e:
                db.rollback()
                _flash_error_from_exception(e, {"route": "auth_request"})
            finally:
                db.close()

        flash(AUTH_REQUEST_MESSAGE, 'success')
        return render_template('auth_request.html', issued_verify_url=issued_verify_url)

    return render_template('auth_request.html', issued_verify_url=issued_verify_url)


@app.route('/auth/login', methods=['GET', 'POST'])
def auth_login():
    next_path = _safe_next_path(request.args.get("next", ""))
    if request.method == 'POST':
        email = _normalize_email(request.form.get('email', ''))
        password = request.form.get('password', '')
        next_path = _safe_next_path(request.form.get("next", ""))

        if not email or not password:
            flash("メールアドレスとパスワードを入力してください。", "warning")
            return render_template('auth_login.html', next_path=next_path, email=email)

        db = get_auth_session()
        try:
            row = db.execute(
                select(User).where(
                    User.email == email,
                    User.is_active.is_(True),
                )
            ).scalar_one_or_none()
            if not row:
                flash("メールアドレスまたはパスワードが正しくありません。", "warning")
                return render_template('auth_login.html', next_path=next_path, email=email)

            raw_user = db.execute(
                select(User.id, User.email, User.role, User.tenant_id).where(User.id == row.id)
            ).one()
            pw_row = db.execute(
                text("SELECT password_hash, must_change_password FROM users WHERE id = :uid"),
                {"uid": row.id},
            ).one_or_none()
            password_hash = (pw_row[0] if pw_row else "") or ""
            must_change_password = bool(pw_row[1]) if pw_row else True

            if not password_hash or not check_password_hash(password_hash, password):
                flash("メールアドレスまたはパスワードが正しくありません。", "warning")
                return render_template('auth_login.html', next_path=next_path, email=email)

            session.clear()
            session['user_id'] = raw_user.id
            session['user_email'] = raw_user.email
            session['user_role'] = raw_user.role
            session['tenant_id'] = raw_user.tenant_id
            session['must_change_password'] = must_change_password

            if must_change_password:
                session["post_change_next"] = next_path or url_for("staff_search")
                return redirect(url_for('auth_change_password'))
            if next_path:
                return redirect(next_path)
            return redirect(url_for('staff_search'))
        except Exception as e:
            _flash_error_from_exception(e, {"route": "auth_login"})
            return render_template('auth_login.html', next_path=next_path, email=email)
        finally:
            db.close()

    return render_template('auth_login.html', next_path=next_path, email="")


@app.route('/auth/verify')
def auth_verify():
    raw_token = request.args.get('token', '').strip()
    if not raw_token:
        flash('ログインURLが不正です。', 'warning')
        return redirect(url_for('auth_login'))

    db = get_auth_session()
    try:
        token = db.execute(
            select(LoginToken).where(
                LoginToken.token_hash == hash_token(raw_token, app.secret_key),
                LoginToken.used_at.is_(None),
                LoginToken.expires_at >= now_utc(),
            )
        ).scalar_one_or_none()

        if not token:
            flash('ログインURLの有効期限切れ、または既に使用済みです。', 'warning')
            return redirect(url_for('auth_login'))

        user = db.get(User, token.user_id)
        if not user or not user.is_active:
            flash('アカウントが無効です。', 'warning')
            return redirect(url_for('auth_login'))

        token.used_at = now_utc()
        db.add(token)
        db.commit()

        session.clear()
        session['user_id'] = user.id
        session['user_email'] = user.email
        session['user_role'] = user.role
        session['tenant_id'] = user.tenant_id
        must_change_row = db.execute(
            text("SELECT must_change_password FROM users WHERE id = :uid"),
            {"uid": user.id},
        ).one_or_none()
        session['must_change_password'] = bool(must_change_row[0]) if must_change_row else True

        if session['must_change_password']:
            session["post_change_next"] = url_for("staff_search")
            return redirect(url_for('auth_change_password'))
        return redirect(url_for('staff_search'))
    except Exception as e:
        db.rollback()
        _flash_error_from_exception(e, {"route": "auth_verify"})
        return redirect(url_for('auth_login'))
    finally:
        db.close()


@app.route('/auth/logout', methods=['POST'])
def auth_logout():
    session.clear()
    flash('ログアウトしました。', 'success')
    return redirect(url_for('auth_login'))


@app.route('/auth/change-password', methods=['GET', 'POST'])
@login_required
def auth_change_password():
    if request.method == 'POST':
        current_password = request.form.get('current_password', '')
        new_password = request.form.get('new_password', '')
        confirm_password = request.form.get('confirm_password', '')

        if not current_password or not new_password or not confirm_password:
            flash("すべての項目を入力してください。", "warning")
            return render_template('auth_change_password.html')
        if new_password != confirm_password:
            flash("新しいパスワードが一致しません。", "warning")
            return render_template('auth_change_password.html')
        if len(new_password) < 8:
            flash("新しいパスワードは8文字以上で入力してください。", "warning")
            return render_template('auth_change_password.html')

        db = get_auth_session()
        try:
            pw_row = db.execute(
                text("SELECT password_hash FROM users WHERE id = :uid"),
                {"uid": session.get("user_id")},
            ).one_or_none()
            current_hash = (pw_row[0] if pw_row else "") or ""
            if not current_hash or not check_password_hash(current_hash, current_password):
                flash("現在のパスワードが正しくありません。", "warning")
                return render_template('auth_change_password.html')

            db.execute(
                text(
                    """
                    UPDATE users
                    SET password_hash = :ph,
                        must_change_password = false,
                        password_changed_at = CURRENT_TIMESTAMP
                    WHERE id = :uid
                    """
                ),
                {
                    "ph": generate_password_hash(new_password),
                    "uid": session.get("user_id"),
                },
            )
            db.commit()
            session["must_change_password"] = False
            flash("パスワードを変更しました。", "success")
            next_path = _safe_next_path(session.pop("post_change_next", "")) or url_for("staff_search")
            return redirect(next_path)
        except Exception as e:
            db.rollback()
            _flash_error_from_exception(e, {"route": "auth_change_password"})
            return render_template('auth_change_password.html')
        finally:
            db.close()

    return render_template('auth_change_password.html')


@app.route('/')
def index():
    if session.get("user_id"):
        return redirect(url_for('staff_search'))
    return redirect(url_for('auth_login'))


@app.route('/admin')
@login_required
@require_admin
def admin_root():
    return redirect(url_for('admin_upload'))


@app.route('/admin/users/new', methods=['GET', 'POST'])
@app.route('/admin/users/create', methods=['GET', 'POST'])
@login_required
def admin_user_new():
    if not _is_platform_admin():
        abort(403)

    tenant_options = _load_tenant_options()
    tenant_ids = {t.id for t in tenant_options}
    preset_tenant_id = _safe_int(request.args.get("tenant_id"))
    selected_tenant_id = preset_tenant_id if preset_tenant_id in tenant_ids else None

    if request.method == 'POST':
        email = _normalize_email(request.form.get("email", ""))
        role = (request.form.get("role", "") or "").strip()
        tenant_id_raw = (request.form.get("tenant_id", "") or "").strip()
        tenant_id = None
        selected_tenant_id = _safe_int(tenant_id_raw)

        if not email:
            flash("email を入力してください。", "warning")
            return render_template(
                'admin_user_new.html',
                tenants=tenant_options,
                selected_tenant_id=selected_tenant_id,
            )
        if role not in {"platform_admin", "tenant_staff"}:
            flash("role が不正です。", "warning")
            return render_template(
                'admin_user_new.html',
                tenants=tenant_options,
                selected_tenant_id=selected_tenant_id,
            )

        if role == "tenant_staff":
            if not tenant_id_raw:
                flash("tenant_staff には tenant_id が必要です。", "warning")
                return render_template(
                    'admin_user_new.html',
                    tenants=tenant_options,
                    selected_tenant_id=selected_tenant_id,
                )
            try:
                tenant_id = int(tenant_id_raw)
            except ValueError:
                tenant_id = None
            if tenant_id not in tenant_ids:
                flash("tenant_id が不正です。", "warning")
                return render_template(
                    'admin_user_new.html',
                    tenants=tenant_options,
                    selected_tenant_id=selected_tenant_id,
                )

        db = get_auth_session()
        try:
            existing_user_id = db.execute(
                text("SELECT id FROM users WHERE lower(email) = :email LIMIT 1"),
                {"email": email},
            ).scalar_one_or_none()
            if existing_user_id is not None:
                flash("その email は既に存在します。", "warning")
                return render_template(
                    'admin_user_new.html',
                    tenants=tenant_options,
                    selected_tenant_id=selected_tenant_id,
                )

            if role == "tenant_staff" and tenant_id is not None:
                active_staff_count = _count_active_tenant_staff(db, tenant_id)
                if active_staff_count >= TENANT_STAFF_LIMIT:
                    flash(
                        f"このテナントは staff 上限（{TENANT_STAFF_LIMIT}件）に達しています。不要なユーザーを無効化するか、プランを変更してください。",
                        "warning",
                    )
                    return render_template(
                        'admin_user_new.html',
                        tenants=tenant_options,
                        selected_tenant_id=selected_tenant_id,
                    )

            temporary_password = _generate_temporary_password()
            insert_sql = text(
                """
                INSERT INTO users (tenant_id, email, role, is_active, password_hash, must_change_password, password_changed_at)
                VALUES (:tenant_id, :email, :role, true, :password_hash, true, NULL)
                RETURNING id
                """
            )
            insert_params = {
                "tenant_id": tenant_id,
                "email": email,
                "role": role,
                "password_hash": generate_password_hash(temporary_password),
            }
            new_user_id = db.execute(insert_sql, insert_params).scalar_one()

            db.commit()

            tenant_name = ""
            if tenant_id is not None:
                for tenant in tenant_options:
                    if tenant.id == tenant_id:
                        tenant_name = tenant.name
                        break

            session["admin_created_user_credentials"] = {
                "id": int(new_user_id),
                "email": email,
                "role": role,
                "tenant": tenant_name,
                "temporary_password": temporary_password,
            }
            flash("ユーザーを作成しました。仮パスワードは次のページで1回のみ表示されます。", "success")
            return redirect(url_for('admin_user_created', user_id=int(new_user_id)))
        except Exception as e:
            db.rollback()
            _flash_error_from_exception(e, {"route": "admin_user_new", "email": email, "role": role})
            return render_template(
                'admin_user_new.html',
                tenants=tenant_options,
                selected_tenant_id=selected_tenant_id,
            )
        finally:
            db.close()

    return render_template(
        'admin_user_new.html',
        tenants=tenant_options,
        selected_tenant_id=selected_tenant_id,
    )


@app.route('/admin/users/created/<int:user_id>', methods=['GET'])
@login_required
@require_admin
def admin_user_created(user_id: int):
    created_notice = None
    one_time_credentials = session.get("admin_created_user_credentials")
    if one_time_credentials and int(one_time_credentials.get("id", 0) or 0) == user_id:
        created_notice = one_time_credentials
        session.pop("admin_created_user_credentials", None)

    user_summary = None
    db = get_auth_session()
    try:
        row = db.execute(
            select(User, Tenant)
            .outerjoin(Tenant, User.tenant_id == Tenant.id)
            .where(User.id == user_id)
        ).one_or_none()
    finally:
        db.close()

    if row:
        user, tenant = row
        user_summary = {
            "id": user.id,
            "email": user.email,
            "role": user.role,
            "tenant": tenant.name if tenant else "",
        }

    return render_template(
        "admin_user_created.html",
        user_id=user_id,
        created_notice=created_notice,
        user_summary=user_summary,
    )


@app.route('/admin/users')
@login_required
@require_admin
def admin_users():
    allowed_sorts = {"email", "tenant", "role", "active", "created_at"}
    sort, direction = _parse_sort_params(
        request.args.get("sort"),
        request.args.get("dir"),
        allowed_sorts,
        default_sort="created_at",
        default_dir="desc",
    )

    order_columns = {
        "email": User.email,
        "tenant": Tenant.name,
        "role": User.role,
        "active": User.is_active,
        "created_at": User.created_at,
    }
    order_column = order_columns[sort]
    order_expr = order_column.asc() if direction == "asc" else order_column.desc()

    db = get_auth_session()
    try:
        rows = db.execute(
            select(User, Tenant)
            .outerjoin(Tenant, User.tenant_id == Tenant.id)
            .order_by(order_expr, User.id.asc())
        ).all()
    finally:
        db.close()

    users = []
    for user, tenant in rows:
        users.append(
            {
                "id": user.id,
                "email": user.email,
                "role": user.role,
                "tenant_id": user.tenant_id,
                "tenant_name": tenant.name if tenant else "",
                "is_active": bool(user.is_active),
                "created_at": user.created_at,
            }
        )

    reset_password_notice = session.pop("reset_password_notice", None)
    return render_template(
        "admin_users.html",
        users=users,
        sort=sort,
        direction=direction,
        current_path=request.full_path.rstrip("?"),
        reset_password_notice=reset_password_notice,
    )


@app.route('/admin/users/<int:user_id>/edit')
@login_required
@require_admin
def admin_user_edit(user_id: int):
    reset_password_notice = session.pop("reset_password_notice", None)
    db = get_auth_session()
    try:
        row = db.execute(
            select(User, Tenant)
            .outerjoin(Tenant, User.tenant_id == Tenant.id)
            .where(User.id == user_id)
        ).one_or_none()
    finally:
        db.close()

    if not row:
        flash("対象ユーザーが見つかりません。", "warning")
        return redirect(url_for("admin_users"))

    user, tenant = row
    return render_template(
        "admin_user_edit.html",
        user=user,
        tenant_name=(tenant.name if tenant else ""),
        next_path=_safe_next_path(request.args.get("next", "")) or url_for("admin_users"),
        reset_password_notice=reset_password_notice,
    )


@app.route('/admin/users/<int:user_id>/deactivate', methods=['POST'])
@login_required
@require_admin
def admin_user_deactivate(user_id: int):
    next_path = _safe_next_path(request.form.get("next", "")) or url_for("admin_users")
    db = get_auth_session()
    try:
        user = db.get(User, user_id)
        if not user:
            flash("対象ユーザーが見つかりません。", "warning")
            return redirect(next_path)
        if not user.is_active:
            flash("このユーザーは既に無効です。", "warning")
            return redirect(next_path)
        if user.role == "platform_admin":
            active_admin_count = _count_active_platform_admins(db)
            if active_admin_count <= 1:
                flash("有効な platform_admin が1人のみのため、このユーザーは無効化できません。", "warning")
                return redirect(next_path)
        user.is_active = False
        db.add(user)
        db.commit()
        flash("ユーザーを無効化しました。", "success")
    except Exception as e:
        db.rollback()
        _flash_error_from_exception(e, {"route": "admin_user_deactivate", "user_id": user_id})
    finally:
        db.close()
    return redirect(next_path)


@app.route('/admin/users/<int:user_id>/activate', methods=['POST'])
@login_required
@require_admin
def admin_user_activate(user_id: int):
    next_path = _safe_next_path(request.form.get("next", "")) or url_for("admin_users")
    db = get_auth_session()
    try:
        row = db.execute(
            select(User).where(User.id == user_id)
        ).scalar_one_or_none()
        if not row:
            flash("対象ユーザーが見つかりません。", "warning")
            return redirect(next_path)
        if row.role == "tenant_staff" and row.tenant_id is not None and not row.is_active:
            active_staff_count = _count_active_tenant_staff(db, row.tenant_id)
            if active_staff_count >= TENANT_STAFF_LIMIT:
                flash(
                    f"このテナントは staff 上限（{TENANT_STAFF_LIMIT}件）に達しています。不要なユーザーを無効化するか、プランを変更してください。",
                    "warning",
                )
                return redirect(next_path)
        row.is_active = True
        db.add(row)
        db.commit()
        flash("ユーザーを有効化しました。", "success")
    except Exception as e:
        db.rollback()
        _flash_error_from_exception(e, {"route": "admin_user_activate", "user_id": user_id})
    finally:
        db.close()
    return redirect(next_path)


@app.route('/admin/tenants/new', methods=['GET', 'POST'])
@login_required
def admin_tenant_new():
    if not _is_platform_admin():
        abort(403)

    if request.method == 'POST':
        tenant_name = (request.form.get("name", "") or "").strip()
        plan = (request.form.get("plan", "A") or "").strip().upper()
        if not tenant_name:
            flash("テナント名を入力してください。", "warning")
            return render_template(
                'admin_tenant_new.html',
                tenant_name=tenant_name,
                plan=plan,
            )
        if plan not in {"A", "B"}:
            flash("plan が不正です。", "warning")
            return render_template(
                'admin_tenant_new.html',
                tenant_name=tenant_name,
                plan=plan,
            )

        db = get_auth_session()
        try:
            new_tenant_id = db.execute(
                text("INSERT INTO tenants (name, plan) VALUES (:name, :plan) RETURNING id"),
                {"name": tenant_name, "plan": plan},
            ).scalar_one()
            db.commit()
            flash("テナントを作成しました。続けてユーザーを追加してください。", "success")
            return redirect(url_for('admin_tenant_created', tenant_id=int(new_tenant_id)))
        except Exception as e:
            db.rollback()
            _flash_error_from_exception(e, {"route": "admin_tenant_new", "name": tenant_name, "plan": plan})
            return render_template(
                'admin_tenant_new.html',
                tenant_name=tenant_name,
                plan=plan,
            )
        finally:
            db.close()

    return render_template(
        'admin_tenant_new.html',
        tenant_name="",
        plan="A",
    )


@app.route('/admin/tenants/<int:tenant_id>/created')
@login_required
@require_admin
def admin_tenant_created(tenant_id: int):
    db = get_auth_session()
    try:
        tenant = db.get(Tenant, tenant_id)
    finally:
        db.close()

    if not tenant:
        flash("対象テナントが見つかりません。", "warning")
        return redirect(url_for("admin_tenants"))
    return render_template("admin_tenant_created.html", tenant=tenant)


@app.route('/admin/tenants')
@login_required
@require_admin
def admin_tenants():
    allowed_sorts = {"id", "name", "plan", "created_at"}
    sort, direction = _parse_sort_params(
        request.args.get("sort"),
        request.args.get("dir"),
        allowed_sorts,
        default_sort="id",
        default_dir="asc",
    )

    order_columns = {
        "id": Tenant.id,
        "name": Tenant.name,
        "plan": Tenant.plan,
        "created_at": Tenant.created_at,
    }
    order_column = order_columns[sort]
    order_expr = order_column.asc() if direction == "asc" else order_column.desc()

    db = get_auth_session()
    try:
        tenants = list(db.execute(select(Tenant).order_by(order_expr, Tenant.id.asc())).scalars())
    finally:
        db.close()

    return render_template(
        "admin_tenants.html",
        tenants=tenants,
        sort=sort,
        direction=direction,
    )


@app.route('/admin/tenants/<int:tenant_id>/edit', methods=['GET', 'POST'])
@login_required
@require_admin
def admin_tenant_edit(tenant_id: int):
    db = get_auth_session()
    try:
        tenant = db.get(Tenant, tenant_id)
        if not tenant:
            flash("対象テナントが見つかりません。", "warning")
            return redirect(url_for("admin_tenants"))

        if request.method == "POST":
            name = (request.form.get("name", "") or "").strip()
            plan = (request.form.get("plan", "") or "").strip().upper()
            if not name:
                flash("テナント名を入力してください。", "warning")
                return render_template("admin_tenant_edit.html", tenant=tenant)
            if plan not in {"A", "B"}:
                flash("plan が不正です。", "warning")
                return render_template("admin_tenant_edit.html", tenant=tenant)

            tenant.name = name
            tenant.plan = plan
            db.add(tenant)
            db.commit()
            flash("テナント情報を更新しました。", "success")
            return redirect(url_for("admin_tenants"))
    except Exception as e:
        db.rollback()
        _flash_error_from_exception(e, {"route": "admin_tenant_edit", "tenant_id": tenant_id})
        return redirect(url_for("admin_tenants"))
    finally:
        db.close()

    return render_template("admin_tenant_edit.html", tenant=tenant)


@app.route('/staff')
@login_required
def staff_root():
    return redirect(url_for('staff_search'))


@app.route('/admin/upload', methods=['GET', 'POST'])
@login_required
@require_admin
def admin_upload():
    tenant_options = _load_tenant_options()
    staff_users = _load_resettable_staff_users()
    tenant_ids = {t.id for t in tenant_options}
    reset_password_notice = session.pop("reset_password_notice", None)
    selected_tenant_id_raw = (request.form.get("tenant_id") if request.method == "POST" else request.args.get("tenant_id", "")).strip()
    selected_tenant_id = None
    if selected_tenant_id_raw:
        try:
            selected_tenant_id = int(selected_tenant_id_raw)
        except ValueError:
            selected_tenant_id = None

    if request.method == 'POST':
        if selected_tenant_id is None or selected_tenant_id not in tenant_ids:
            _flash_error_from_hint("tenant invalid", {"route": "admin_upload", "tenant_id": selected_tenant_id_raw})
            return redirect(url_for('admin_upload'))

        file = request.files.get('csv_file')

        if not file or file.filename == '':
            _flash_error_from_hint("csv invalid: file missing", {"route": "admin_upload"})
            return redirect(url_for('admin_upload'))

        if not file.filename.endswith('.csv'):
            _flash_error_from_hint("csv invalid: extension", {"route": "admin_upload", "filename": file.filename})
            return redirect(url_for('admin_upload'))

        conn = None
        try:
            raw = file.read()
            text = raw.decode('utf-8-sig')
            stream = io.StringIO(text)
            reader = csv.DictReader(stream)

            csv_columns = reader.fieldnames
            if csv_columns is None:
                _flash_error_from_hint("csv invalid: empty", {"route": "admin_upload", "filename": file.filename})
                return redirect(url_for('admin_upload'))

            csv_columns = [col.strip() for col in csv_columns]

            missing_columns = set(REQUIRED_CSV_COLUMNS) - set(csv_columns)
            if missing_columns:
                _flash_error_from_hint("csv invalid: missing columns", {"missing_columns": sorted(missing_columns)})
                return redirect(url_for('admin_upload'))

            extra_columns = set(csv_columns) - set(REQUIRED_CSV_COLUMNS)
            if extra_columns:
                _flash_error_from_hint("csv invalid: extra columns", {"extra_columns": sorted(extra_columns)})
                return redirect(url_for('admin_upload'))

            conn = get_db_connection()
            cursor = conn.cursor()

            total_rows = 0
            inserted_count = 0
            updated_count = 0
            error_count = 0
            error_details = []
            changed_count = 0
            override_conflict_count = 0
            sample_diffs = []

            fields = [
                'price_jpy', 'case_size_mm', 'movement', 'case_material',
                'bracelet_strap', 'dial_color', 'water_resistance_m', 'buckle',
                'warranty_years', 'collection', 'movement_caliber',
                'case_thickness_mm', 'lug_width_mm', 'remarks'
            ]

            for row_num, row in enumerate(reader, start=2):
                total_rows += 1
                row = {k.strip(): (v.strip() if v else '') for k, v in row.items()}

                brand = normalize_brand(row.get('brand', ''))
                reference = normalize_reference(row.get('reference', ''))

                if not brand or not reference:
                    error_count += 1
                    error_details.append(f'行{row_num}: brandまたはreferenceが空です')
                    continue

                data = {f: row.get(f, '') for f in fields}
                data['brand'] = brand
                data['reference'] = reference

                try:
                    cursor.execute(
                        "SELECT * FROM master_products WHERE tenant_id = ? AND brand = ? AND reference = ?",
                        (selected_tenant_id, brand, reference)
                    )
                    existing = cursor.fetchone()

                    cursor.execute(
                        "SELECT 1 FROM product_overrides WHERE tenant_id = ? AND brand = ? AND reference = ?",
                        (selected_tenant_id, brand, reference)
                    )
                    override_exists = cursor.fetchone() is not None

                    row_changed = False
                    row_has_override_conflict = False
                    row_diffs = []

                    if existing:
                        for f in fields:
                            old_value = existing[f] or ''
                            new_value = data[f] or ''
                            if old_value != new_value:
                                row_changed = True
                                diff_info = {'field': f, 'old': old_value, 'new': new_value}
                                if override_exists:
                                    row_has_override_conflict = True
                                    diff_info['override_exists'] = True
                                row_diffs.append(diff_info)

                        if row_changed:
                            changed_count += 1
                            if row_has_override_conflict:
                                override_conflict_count += 1
                            if len(sample_diffs) < 10:
                                sample_diffs.append({
                                    'brand': brand,
                                    'reference': reference,
                                    'diffs': row_diffs
                                })

                    cursor.execute('''
                        INSERT INTO master_products
                        (tenant_id, brand, reference, price_jpy, case_size_mm, movement, case_material,
                         bracelet_strap, dial_color, water_resistance_m, buckle, warranty_years,
                         collection, movement_caliber, case_thickness_mm, lug_width_mm, remarks, updated_at)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
                        ON CONFLICT(tenant_id, brand, reference) DO UPDATE SET
                            price_jpy = excluded.price_jpy,
                            case_size_mm = excluded.case_size_mm,
                            movement = excluded.movement,
                            case_material = excluded.case_material,
                            bracelet_strap = excluded.bracelet_strap,
                            dial_color = excluded.dial_color,
                            water_resistance_m = excluded.water_resistance_m,
                            buckle = excluded.buckle,
                            warranty_years = excluded.warranty_years,
                            collection = excluded.collection,
                            movement_caliber = excluded.movement_caliber,
                            case_thickness_mm = excluded.case_thickness_mm,
                            lug_width_mm = excluded.lug_width_mm,
                            remarks = excluded.remarks,
                            updated_at = CURRENT_TIMESTAMP
                    ''', (
                        selected_tenant_id, brand, reference, data['price_jpy'], data['case_size_mm'],
                        data['movement'], data['case_material'], data['bracelet_strap'],
                        data['dial_color'], data['water_resistance_m'], data['buckle'],
                        data['warranty_years'], data['collection'], data['movement_caliber'],
                        data['case_thickness_mm'], data['lug_width_mm'], data['remarks']
                    ))

                    if existing:
                        updated_count += 1
                    else:
                        inserted_count += 1

                except Exception as e:
                    error_count += 1
                    error_details.append(f'行{row_num}: データベースエラー - {str(e)}')

            error_details_str = '\n'.join(error_details) if error_details else ''
            sample_diffs_str = json.dumps(sample_diffs, ensure_ascii=False) if sample_diffs else None

            cursor.execute('''
                INSERT INTO master_uploads
                (filename, total_rows, inserted_count, updated_count, error_count, error_details,
                 changed_count, override_conflict_count, sample_diffs)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            ''', (
                file.filename, total_rows, inserted_count, updated_count, error_count, error_details_str,
                changed_count, override_conflict_count, sample_diffs_str
            ))

            conn.commit()

            flash(
                f'インポート完了: 総行数={total_rows}, 新規={inserted_count}, 更新={updated_count}, '
                f'エラー={error_count}, 変更={changed_count}, オーバーライド競合={override_conflict_count}',
                'success'
            )
            if error_details:
                error_id = make_error_id()
                log_exception(
                    app.logger,
                    RuntimeError('admin_upload had row errors'),
                    error_id,
                    {
                        "route": "admin_upload",
                        "filename": file.filename,
                        "total_rows": total_rows,
                        "error_count": error_count,
                        "first_errors": error_details[:5],
                    },
                )
                flash(to_user_message(RuntimeError('unknown: admin_upload had row errors'), error_id), 'warning')

        except Exception as e:
            _flash_error_from_exception(e, {"route": "admin_upload", "filename": getattr(file, "filename", "")})
        finally:
            try:
                if conn:
                    conn.close()
            except Exception:
                pass

        return redirect(url_for('admin_upload', tenant_id=selected_tenant_id))

    conn = get_db_connection()
    latest_upload = conn.execute('''
        SELECT * FROM master_uploads
        ORDER BY uploaded_at DESC LIMIT 1
    ''').fetchone()

    sample_diffs = None
    if latest_upload and latest_upload['sample_diffs']:
        try:
            sample_diffs = json.loads(latest_upload['sample_diffs'])
        except Exception:
            sample_diffs = None

    conn.close()
    return render_template(
        'admin.html',
        latest_upload=latest_upload,
        sample_diffs=sample_diffs,
        tenants=tenant_options,
        staff_users=staff_users,
        reset_password_notice=reset_password_notice,
        selected_tenant_id=selected_tenant_id,
    )


@app.route('/admin/users/<int:user_id>/reset-password', methods=['POST'])
@login_required
@require_admin
def admin_reset_password(user_id: int):
    next_path = _safe_next_path(request.form.get("next", "")) or url_for("admin_users")
    db = get_auth_session()
    try:
        user = db.execute(
            select(User).where(
                User.id == user_id,
                User.is_active.is_(True),
            )
        ).scalar_one_or_none()
        if not user:
            flash("対象ユーザーが見つからないか、無効化されています。", "warning")
            return redirect(next_path)

        temporary_password = _generate_temporary_password()
        db.execute(
            text(
                """
                UPDATE users
                SET password_hash = :password_hash,
                    must_change_password = true,
                    password_changed_at = NULL
                WHERE id = :user_id
                """
            ),
            {
                "password_hash": generate_password_hash(temporary_password),
                "user_id": user.id,
            },
        )
        db.commit()
        session["reset_password_notice"] = {
            "email": user.email,
            "temporary_password": temporary_password,
        }
        flash("仮パスワードを再発行しました。以下の表示はこの1回のみです。", "success")
    except Exception as e:
        db.rollback()
        _flash_error_from_exception(e, {"route": "admin_reset_password", "user_id": user_id})
    finally:
        db.close()

    return redirect(next_path)


@app.route('/staff/references', methods=['GET'])
@login_required
def staff_references():
    tenant_id, err = _staff_tenant_or_403_json()
    if err:
        return err

    brand = normalize_brand(request.args.get('brand', ''))
    if not brand:
        return jsonify({"brand": "", "count": 0, "items": []})

    count, items = get_references_by_brand(brand, tenant_id=tenant_id)
    return jsonify({"brand": brand, "count": count, "items": items})


@app.route('/staff/search', methods=['GET', 'POST'])
@login_required
def staff_search():
    tenant_id, tenant_err = _resolve_staff_tenant_id()
    if tenant_id is None:
        if _is_platform_admin():
            warning_message = "指定されたテナントは存在しません。" if tenant_err == "tenant_invalid" else "テナントを選択してください。"
            flash(warning_message, "warning")
            if request.method == 'POST':
                return redirect(url_for('staff_search'))
            mk, used, rem = get_quota_view()
            return render_template(
                'search.html',
                brands=[],
                recent_generations=[],
                brand="",
                reference="",
                master=None,
                override=None,
                canonical={},
                overridden_fields=[],
                warnings=["テナントを選択してください。"],
                override_warning=None,
                import_conflict_warning=None,
                history=[],
                staff_tenant_missing=True,
                plan_mode=PLAN_MODE,
                monthly_limit=MONTHLY_LIMIT,
                monthly_used=used,
                monthly_remaining=rem,
                month_key=mk,
                total_product_count=0,
                brand_summaries=[],
                combined_reference_chars=0,
                combined_reference_preview="",
                reference_urls_debug=[],
                llm_client_file=llmc.__file__,
                raw_urls_debug=[],
                similarity_percent=0,
                similarity_level="blue",
                saved_article_id=None,
                reference_registration_count=None,
                staff_additional_input="",
            )
        flash("テナント未所属のため staff 機能を利用できません。", "warning")
        return redirect(url_for("auth_login"))

    fields = [
        'price_jpy', 'case_size_mm', 'movement', 'case_material',
        'bracelet_strap', 'dial_color', 'water_resistance_m', 'buckle',
        'warranty_years', 'collection', 'movement_caliber',
        'case_thickness_mm', 'lug_width_mm', 'remarks',
    ]

    # NOTE: do NOT put plan_mode/monthly_* here (avoid duplicate keyword bugs)
    debug_defaults = {
        "combined_reference_chars": 0,
        "combined_reference_preview": "",
        "reference_urls_debug": [],
        "llm_client_file": llmc.__file__,
        "raw_urls_debug": [],
        "similarity_percent": 0,
        "similarity_level": "blue",
        "saved_article_id": None,
        "staff_additional_input": "",
    }

    mk0, _, _ = get_quota_view()
    total_product_count, brand_summaries = get_brand_summary_view(mk0, tenant_id=tenant_id)
    summary_defaults = {
        "total_product_count": total_product_count,
        "brand_summaries": brand_summaries,
    }

    if request.method == 'POST':
        action = request.form.get('action', '').strip()

        if action == 'search':
            brand = normalize_brand(request.form.get('brand', ''))
            reference = normalize_reference(request.form.get('reference', ''))
            if not brand or not reference:
                mk, used, rem = get_quota_view()
                return render_template(
                    'search.html',
                    brands=get_brands(tenant_id=tenant_id),
                    recent_generations=get_recent_generations(limit=10, tenant_id=tenant_id),
                    plan_mode=PLAN_MODE, monthly_limit=MONTHLY_LIMIT, monthly_used=used, monthly_remaining=rem, month_key=mk,
                    reference_registration_count=None,
                    **summary_defaults,
                    **debug_defaults
                )
            return redirect(url_for('staff_search', brand=brand, reference=reference))

        if action == 'save_override':
            brand = normalize_brand(request.form.get('brand', ''))
            reference = normalize_reference(request.form.get('reference', ''))
            if not brand or not reference:
                mk, used, rem = get_quota_view()
                return render_template(
                    'search.html',
                    brands=get_brands(tenant_id=tenant_id),
                    recent_generations=get_recent_generations(limit=10, tenant_id=tenant_id),
                    plan_mode=PLAN_MODE, monthly_limit=MONTHLY_LIMIT, monthly_used=used, monthly_remaining=rem, month_key=mk,
                    reference_registration_count=None,
                    **summary_defaults,
                    **debug_defaults
                )

            data = {'brand': brand, 'reference': reference}
            for f in fields:
                data[f] = request.form.get(f, '').strip()

            conn = get_db_connection()
            try:
                cursor = conn.cursor()
                cursor.execute('''
                    INSERT INTO product_overrides
                    (tenant_id, brand, reference, price_jpy, case_size_mm, movement, case_material,
                     bracelet_strap, dial_color, water_resistance_m, buckle, warranty_years,
                     collection, movement_caliber, case_thickness_mm, lug_width_mm, remarks, updated_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
                    ON CONFLICT(tenant_id, brand, reference) DO UPDATE SET
                        price_jpy = excluded.price_jpy,
                        case_size_mm = excluded.case_size_mm,
                        movement = excluded.movement,
                        case_material = excluded.case_material,
                        bracelet_strap = excluded.bracelet_strap,
                        dial_color = excluded.dial_color,
                        water_resistance_m = excluded.water_resistance_m,
                        buckle = excluded.buckle,
                        warranty_years = excluded.warranty_years,
                        collection = excluded.collection,
                        movement_caliber = excluded.movement_caliber,
                        case_thickness_mm = excluded.case_thickness_mm,
                        lug_width_mm = excluded.lug_width_mm,
                        remarks = excluded.remarks,
                        updated_at = CURRENT_TIMESTAMP
                ''', (
                    tenant_id, data['brand'], data['reference'], data['price_jpy'], data['case_size_mm'],
                    data['movement'], data['case_material'], data['bracelet_strap'],
                    data['dial_color'], data['water_resistance_m'], data['buckle'],
                    data['warranty_years'], data['collection'], data['movement_caliber'],
                    data['case_thickness_mm'], data['lug_width_mm'], data['remarks']
                ))
                conn.commit()
            finally:
                try:
                    conn.close()
                except Exception:
                    pass

            flash('オーバーライドを保存しました', 'success')
            return redirect(url_for('staff_search', brand=brand, reference=reference))

        if action == 'delete_override':
            brand = normalize_brand(request.form.get('brand', ''))
            reference = normalize_reference(request.form.get('reference', ''))
            if not brand or not reference:
                _flash_error_from_hint("unknown: missing brand/reference", {"route": "staff_search", "action": "delete_override"})
                return redirect(url_for('staff_search'))

            conn = get_db_connection()
            try:
                conn.execute('''
                    DELETE FROM product_overrides
                    WHERE tenant_id = ? AND brand = ? AND reference = ?
                ''', (tenant_id, brand, reference))
                conn.commit()
            finally:
                try:
                    conn.close()
                except Exception:
                    pass

            flash('オーバーライドを解除しました（マスタに戻しました）', 'success')
            return redirect(url_for('staff_search', brand=brand, reference=reference))

        # ----------------------------
        # Generate
        # ----------------------------
        if action == 'generate_dummy':
            brand = normalize_brand(request.form.get('brand', ''))
            reference = normalize_reference(request.form.get('reference', ''))
            if not brand or not reference:
                _flash_error_from_hint("unknown: missing brand/reference", {"route": "staff_search", "action": "generate_dummy"})
                return redirect(url_for('staff_search'))
            staff_additional_input_in_form = request.form.get('staff_additional_input', '').strip()

            raw_urls = [
                request.form.get('reference_url_1', '').strip(),
                request.form.get('reference_url_2', '').strip(),
                request.form.get('reference_url_3', '').strip(),
            ]
            raw_urls = [u for u in raw_urls if u]

            if not raw_urls:
                auto_urls, _auto_debug = discover_reference_urls(brand, reference, max_urls=3)
                reference_urls = auto_urls[:3]
            else:
                reference_urls = raw_urls[:3]

            conn = get_db_connection()
            try:
                master = conn.execute('''
                    SELECT * FROM master_products
                    WHERE tenant_id = ? AND brand = ? AND reference = ?
                ''', (tenant_id, brand, reference)).fetchone()

                override = conn.execute('''
                    SELECT * FROM product_overrides
                    WHERE tenant_id = ? AND brand = ? AND reference = ?
                ''', (tenant_id, brand, reference)).fetchone()

                staff_row = conn.execute(
                    '''
                    SELECT content
                    FROM staff_additional_inputs
                    WHERE tenant_id = ? AND brand = ? AND reference = ?
                    ''',
                    (tenant_id, brand, reference),
                ).fetchone()
                saved_staff_additional_input = (staff_row['content'] if staff_row and staff_row['content'] else '').strip()
                if staff_additional_input_in_form != saved_staff_additional_input:
                    if staff_additional_input_in_form:
                        flash("スタッフの体験談を追加して文章を生成します", "warning")
                    current_user_id = _safe_int(session.get("user_id"))
                    _save_staff_additional_input(
                        conn=conn,
                        tenant_id=tenant_id,
                        brand=brand,
                        reference=reference,
                        content=staff_additional_input_in_form,
                        updated_by_user_id=current_user_id,
                    )
                    conn.commit()
                    saved_staff_additional_input = staff_additional_input_in_form

                canonical = {}
                for f in fields:
                    ov = override[f] if override and override[f] else ''
                    ms = master[f] if master and master[f] else ''
                    canonical[f] = ov if ov else ms
            except Exception as e:
                _flash_error_from_exception(
                    e,
                    {"route": "staff_search", "action": "save_staff_additional_input", "brand": brand, "reference": reference},
                )
                return redirect(url_for('staff_search', brand=brand, reference=reference))
            finally:
                try:
                    conn.close()
                except Exception:
                    pass

            tone_ui = request.form.get('tone', 'practical').strip()
            tone_map = {
                "practical": "practical",
                "luxury": "luxury",
                "magazine_story": "magazine_story",
                "casual_friendly": "casual_friendly",
            }
            tone = tone_map.get(tone_ui, "practical")

            include_brand_profile = request.form.get('include_brand_profile') == 'on'
            include_wearing_scenes = request.form.get('include_wearing_scenes') == 'on'

            payload = {
                'product': {'brand': brand, 'reference': reference},
                'facts': canonical,
                'style': {'tone': tone, 'writing_variant_id': 1},
                'options': {
                    'include_brand_profile': include_brand_profile,
                    'include_wearing_scenes': include_wearing_scenes
                },
                'constraints': {'target_intro_chars': 1500, 'max_specs_chars': 1000},
                'staff_additional_input': saved_staff_additional_input,
                'reference_urls': reference_urls,
                'reference_url': reference_urls[0] if reference_urls else "",
            }

            ok, msg = consume_quota_or_block(n=1)
            if not ok:
                _flash_error_from_hint(msg, {"route": "staff_search", "action": "generate_dummy", "brand": brand, "reference": reference})
                return redirect(url_for('staff_search', brand=brand, reference=reference))

            generation_elapsed_sec = None
            try:
                start = time.perf_counter()
                intro_text, specs_text, ref_meta = llmc.generate_article(payload, rewrite_mode="none")
                generation_elapsed_sec = time.perf_counter() - start
            except Exception as e:
                _flash_error_from_exception(e, {"route": "staff_search", "action": "generate_dummy", "brand": brand, "reference": reference})
                return redirect(url_for('staff_search', brand=brand, reference=reference))

            combined_reference_chars = int(ref_meta.get("combined_reference_chars", 0) or 0)
            combined_reference_preview = ref_meta.get("combined_reference_preview", "") or ""
            reference_urls_debug = ref_meta.get("reference_urls_debug", []) or []
            selected_reference_url = ref_meta.get("selected_reference_url", "") or ""
            selected_reference_reason = ref_meta.get("selected_reference_reason", "") or ""

            similarity_percent = int(ref_meta.get("similarity_percent", 0) or 0)
            similarity_level = (ref_meta.get("similarity_level") or "blue").strip() or "blue"
            rewrite_applied = bool(ref_meta.get("rewrite_applied", False))

            payload["selected_reference_url"] = selected_reference_url
            payload["selected_reference_reason"] = selected_reference_reason
            payload["combined_reference_chars"] = combined_reference_chars
            payload["combined_reference_preview"] = combined_reference_preview
            payload["reference_urls_debug"] = reference_urls_debug
            payload["similarity_percent"] = similarity_percent
            payload["similarity_level"] = similarity_level
            payload["rewrite_applied"] = rewrite_applied
            payload["elapsed_ms"] = int(round((generation_elapsed_sec or 0) * 1000))

            saved_article_id = None
            conn_save = None
            try:
                conn_save = get_db_connection()

                payload["rewrite_depth"] = 0
                payload["rewrite_parent_id"] = None
                payload["rewrite_applied"] = False

                cur = conn_save.execute("""
                    INSERT INTO generated_articles
                    (tenant_id, brand, reference, payload_json, intro_text, specs_text, rewrite_depth, rewrite_parent_id)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    RETURNING id
                """, (
                    tenant_id,
                    brand,
                    reference,
                    json.dumps(payload, ensure_ascii=False),
                    intro_text,
                    specs_text,
                    0,
                    None
                ))
                conn_save.commit()
                inserted = cur.fetchone()
                if isinstance(inserted, dict):
                    saved_article_id = inserted.get("id")
                elif inserted:
                    saved_article_id = inserted[0]
                else:
                    saved_article_id = getattr(cur, "lastrowid", None)
            except Exception as e:
                _flash_error_from_exception(e, {"route": "staff_search", "action": "save_generated_article", "brand": brand, "reference": reference})
            finally:
                try:
                    if conn_save:
                        conn_save.close()
                except Exception:
                    pass

            conn = get_db_connection()
            try:
                master = conn.execute('''
                    SELECT * FROM master_products
                    WHERE tenant_id = ? AND brand = ? AND reference = ?
                ''', (tenant_id, brand, reference)).fetchone()

                override = conn.execute('''
                    SELECT * FROM product_overrides
                    WHERE tenant_id = ? AND brand = ? AND reference = ?
                ''', (tenant_id, brand, reference)).fetchone()

                canonical = {}
                overridden_fields = set()
                for f in fields:
                    ov = override[f] if override and override[f] else ''
                    ms = master[f] if master and master[f] else ''
                    canonical[f] = ov if ov else ms
                    if ov:
                        overridden_fields.add(f)

                history_rows = conn.execute("""
                    SELECT id, intro_text, specs_text, payload_json, created_at, rewrite_depth, rewrite_parent_id
                    FROM generated_articles
                    WHERE tenant_id = ? AND brand = ? AND reference = ?
                    ORDER BY created_at DESC, id DESC
                    LIMIT 5
                """, (tenant_id, brand, reference)).fetchall()
            finally:
                try:
                    conn.close()
                except Exception:
                    pass
            history = _build_history_rows(history_rows)

            mk, used, rem = get_quota_view()

            return render_template(
                'search.html',
                brands=get_brands(tenant_id=tenant_id),
                recent_generations=get_recent_generations(limit=10, tenant_id=tenant_id),
                brand=brand,
                reference=reference,
                master=master,
                override=override,
                staff_additional_input=saved_staff_additional_input,
                canonical=canonical,
                overridden_fields=overridden_fields,

                generated_intro_text=intro_text,
                generated_specs_text=specs_text,
                generation_tone=tone,
                generation_include_brand_profile=include_brand_profile,
                generation_include_wearing_scenes=include_wearing_scenes,
                generation_reference_urls=reference_urls,

                selected_reference_url=selected_reference_url,
                selected_reference_reason=selected_reference_reason,

                history=history,
                combined_reference_chars=combined_reference_chars,
                combined_reference_preview=combined_reference_preview,
                reference_urls_debug=reference_urls_debug,
                llm_client_file=llmc.__file__,
                raw_urls_debug=(raw_urls if raw_urls else reference_urls),

                similarity_percent=similarity_percent,
                similarity_level=similarity_level,
                generation_elapsed_sec=generation_elapsed_sec,

                saved_article_id=saved_article_id,
                rewrite_depth=0,

                plan_mode=PLAN_MODE,
                monthly_limit=MONTHLY_LIMIT,
                monthly_used=used,
                monthly_remaining=rem,
                month_key=mk,
                reference_registration_count=_count_master_products_for_reference(tenant_id, brand, reference),
                **summary_defaults,
            )

        # ----------------------------
        # Rewrite once (max 1 per source id)
        # ----------------------------
        if action == 'rewrite_once':
            brand = normalize_brand(request.form.get('brand', ''))
            reference = normalize_reference(request.form.get('reference', ''))
            source_article_id = request.form.get('source_article_id', '').strip()

            if not (brand and reference and source_article_id.isdigit()):
                _flash_error_from_hint("unknown: invalid rewrite target", {"source_article_id": source_article_id})
                return redirect(url_for('staff_search', brand=brand, reference=reference))

            conn = get_db_connection()
            row = conn.execute(
                "SELECT * FROM generated_articles WHERE id = ? AND tenant_id = ?",
                (int(source_article_id), tenant_id)
            ).fetchone()

            if not row:
                conn.close()
                _flash_error_from_hint("unknown: rewrite source not found", {"source_article_id": source_article_id})
                return redirect(url_for('staff_search', brand=brand, reference=reference))

            payload = {}
            try:
                payload = json.loads(row['payload_json']) if row['payload_json'] else {}
            except Exception:
                payload = {}

            # Server-side guard: same source id can be rewritten only once
            already = conn.execute(
                "SELECT 1 FROM generated_articles WHERE rewrite_parent_id = ? AND tenant_id = ? LIMIT 1",
                (int(source_article_id), tenant_id)
            ).fetchone()
            if already:
                conn.close()
                flash('この履歴は既に言い換え済みのため、再度の言い換えはできません（最大1回）', 'warning')
                return redirect(url_for('staff_search', brand=brand, reference=reference))

            # Prevent rewriting a rewritten record
            src_depth = int(payload.get("rewrite_depth", 0) or 0)
            if src_depth >= 1:
                conn.close()
                flash('この履歴は既に言い換え済みのため、再度の言い換えはできません（最大1回）', 'warning')
                return redirect(url_for('staff_search', brand=brand, reference=reference))

            ok, msg = consume_quota_or_block(n=1)
            if not ok:
                conn.close()
                _flash_error_from_hint(msg, {"route": "staff_search", "action": "rewrite_once", "brand": brand, "reference": reference})
                return redirect(url_for('staff_search', brand=brand, reference=reference))

            rewrite_elapsed_sec = None
            try:
                start = time.perf_counter()
                intro_text, specs_text, ref_meta = llmc.generate_article(payload, rewrite_mode="force")
                rewrite_elapsed_sec = time.perf_counter() - start
            except Exception as e:
                conn.close()
                _flash_error_from_exception(e, {"route": "staff_search", "action": "rewrite_once", "brand": brand, "reference": reference})
                return redirect(url_for('staff_search', brand=brand, reference=reference))

            payload["selected_reference_url"] = ref_meta.get("selected_reference_url", "")
            payload["selected_reference_reason"] = ref_meta.get("selected_reference_reason", "")
            payload["combined_reference_chars"] = ref_meta.get("combined_reference_chars", 0)
            payload["combined_reference_preview"] = ref_meta.get("combined_reference_preview", "")
            payload["reference_urls_debug"] = ref_meta.get("reference_urls_debug", [])

            similarity_percent = int(ref_meta.get("similarity_percent", 0) or 0)
            similarity_level = (ref_meta.get("similarity_level", "blue") or "blue").strip()

            payload["similarity_percent"] = similarity_percent
            payload["similarity_level"] = similarity_level

            payload["rewrite_applied"] = True
            payload["rewrite_depth"] = 1
            payload["rewrite_parent_id"] = int(source_article_id)
            payload["elapsed_ms"] = int(round((rewrite_elapsed_sec or 0) * 1000))

            cur = conn.execute("""
                INSERT INTO generated_articles
                (tenant_id, brand, reference, payload_json, intro_text, specs_text, rewrite_depth, rewrite_parent_id)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                RETURNING id
            """, (
                tenant_id,
                brand,
                reference,
                json.dumps(payload, ensure_ascii=False),
                intro_text,
                specs_text,
                1,
                int(source_article_id)
            ))
            conn.commit()
            inserted = cur.fetchone()
            if isinstance(inserted, dict):
                saved_article_id = inserted.get("id")
            elif inserted:
                saved_article_id = inserted[0]
            else:
                saved_article_id = getattr(cur, "lastrowid", None)

            try:
                master = conn.execute('''
                    SELECT * FROM master_products
                    WHERE tenant_id = ? AND brand = ? AND reference = ?
                ''', (tenant_id, brand, reference)).fetchone()

                override = conn.execute('''
                    SELECT * FROM product_overrides
                    WHERE tenant_id = ? AND brand = ? AND reference = ?
                ''', (tenant_id, brand, reference)).fetchone()

                canonical = {}
                overridden_fields = set()
                for f in fields:
                    ov = override[f] if override and override[f] else ''
                    ms = master[f] if master and master[f] else ''
                    canonical[f] = ov if ov else ms
                    if ov:
                        overridden_fields.add(f)

                history_rows = conn.execute("""
                    SELECT id, intro_text, specs_text, payload_json, created_at, rewrite_depth, rewrite_parent_id
                    FROM generated_articles
                    WHERE tenant_id = ? AND brand = ? AND reference = ?
                    ORDER BY created_at DESC, id DESC
                    LIMIT 5
                """, (tenant_id, brand, reference)).fetchall()
            finally:
                try:
                    conn.close()
                except Exception:
                    pass

            history = _build_history_rows(history_rows)

            mk, used, rem = get_quota_view()

            return render_template(
                'search.html',
                brands=get_brands(tenant_id=tenant_id),
                recent_generations=get_recent_generations(limit=10, tenant_id=tenant_id),
                brand=brand,
                reference=reference,
                master=master,
                override=override,
                staff_additional_input=(payload.get("staff_additional_input") or payload.get("editor_note") or ""),
                canonical=canonical,
                overridden_fields=overridden_fields,

                generated_intro_text=intro_text,
                generated_specs_text=specs_text,

                generation_tone=(payload.get('style', {}) or {}).get('tone'),
                generation_include_brand_profile=(payload.get('options', {}) or {}).get('include_brand_profile'),
                generation_include_wearing_scenes=(payload.get('options', {}) or {}).get('include_wearing_scenes'),
                generation_reference_urls=(payload.get("reference_urls") or []),

                selected_reference_url=payload.get("selected_reference_url", ""),
                selected_reference_reason=payload.get("selected_reference_reason", ""),

                combined_reference_chars=payload.get("combined_reference_chars", 0),
                combined_reference_preview=payload.get("combined_reference_preview", ""),
                reference_urls_debug=payload.get("reference_urls_debug", []),

                llm_client_file=llmc.__file__,
                raw_urls_debug=(payload.get("reference_urls") or []),

                similarity_percent=similarity_percent,
                similarity_level=similarity_level,
                rewrite_elapsed_sec=rewrite_elapsed_sec,

                saved_article_id=saved_article_id,
                rewrite_depth=1,

                plan_mode=PLAN_MODE,
                monthly_limit=MONTHLY_LIMIT,
                monthly_used=used,
                monthly_remaining=rem,
                month_key=mk,
                reference_registration_count=_count_master_products_for_reference(tenant_id, brand, reference),
                **summary_defaults,

                history=history,
            )

        if action == 'regenerate_from_history':
            flash('履歴から再生成は現在停止中です（今は不要なため）', 'warning')
            brand = normalize_brand(request.form.get('brand', ''))
            reference = normalize_reference(request.form.get('reference', ''))
            return redirect(url_for('staff_search', brand=brand, reference=reference))

        _flash_error_from_hint("unknown: unsupported action", {"route": "staff_search", "action": action})
        return redirect(url_for('staff_search'))

    # ----------------------------
    # GET
    # ----------------------------
    mk, used, rem = get_quota_view()

    brand = normalize_brand(request.args.get('brand', ''))
    reference = normalize_reference(request.args.get('reference', ''))
    reference_registration_count = _count_master_products_for_reference(tenant_id, brand, reference)

    master = None
    override = None
    canonical = {}
    overridden_fields = set()
    warnings = []
    override_warning = None
    import_conflict_warning = None
    history = []
    staff_additional_input = ""

    if brand and reference:
        conn = get_db_connection()
        try:
            master = conn.execute('''
                SELECT * FROM master_products
                WHERE tenant_id = ? AND brand = ? AND reference = ?
            ''', (tenant_id, brand, reference)).fetchone()

            override = conn.execute('''
                SELECT * FROM product_overrides
                WHERE tenant_id = ? AND brand = ? AND reference = ?
            ''', (tenant_id, brand, reference)).fetchone()

            staff_row = conn.execute('''
                SELECT content
                FROM staff_additional_inputs
                WHERE tenant_id = ? AND brand = ? AND reference = ?
            ''', (tenant_id, brand, reference)).fetchone()
            staff_additional_input = (staff_row['content'] if staff_row and staff_row['content'] else '').strip()

            for f in fields:
                ov = override[f] if override and override[f] else ''
                ms = master[f] if master and master[f] else ''
                canonical[f] = ov if ov else ms
                if ov:
                    overridden_fields.add(f)

            if not master:
                warnings.append('商品マスタに存在しません。任意入力してください')
            if not canonical.get('price_jpy'):
                warnings.append('price_jpyがマスタとオーバーライドの両方で空です')

            if override:
                override_warning = 'この商品にはオーバーライドが設定されています'

            history_rows = conn.execute("""
                SELECT id, intro_text, specs_text, payload_json, created_at, rewrite_depth, rewrite_parent_id
                FROM generated_articles
                WHERE tenant_id = ? AND brand = ? AND reference = ?
                ORDER BY created_at DESC, id DESC
                LIMIT 5
            """, (tenant_id, brand, reference)).fetchall()
        finally:
            try:
                conn.close()
            except Exception:
                pass
        history = _build_history_rows(history_rows)

    return render_template(
        'search.html',
        brands=get_brands(tenant_id=tenant_id),
        recent_generations=get_recent_generations(limit=10, tenant_id=tenant_id),
        brand=brand,
        reference=reference,
        master=master,
        override=override,
        staff_additional_input=staff_additional_input,
        canonical=canonical,
        overridden_fields=overridden_fields,
        warnings=warnings,
        override_warning=override_warning,
        import_conflict_warning=import_conflict_warning,
        history=history,

        plan_mode=PLAN_MODE,
        monthly_limit=MONTHLY_LIMIT,
        monthly_used=used,
        monthly_remaining=rem,
        month_key=mk,
        reference_registration_count=reference_registration_count,
        **summary_defaults,

        **debug_defaults,
    )


if __name__ == "__main__":
    app.run(debug=False, use_reloader=False, port=5000)
