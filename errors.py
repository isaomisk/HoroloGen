import re
import uuid
from datetime import datetime, timedelta
from typing import Any


def make_error_id() -> str:
    dt = datetime.utcnow() + timedelta(hours=9)
    return f"ERR-{dt.strftime('%Y%m%d')}-{uuid.uuid4().hex[:4].upper()}"


def to_error_code(e: Exception) -> str:
    msg = str(e or "")
    m = msg.lower()

    if "quota" in m or "上限" in msg:
        return "QUOTA"
    if "api key" in m or "anthropic_api_key" in m or "auth" in m or "unauthorized" in m:
        return "API_AUTH"
    if "rate limit" in m or "too many requests" in m or "credit balance is too low" in m or "billing" in m:
        return "RATE_CREDIT"
    if "timeout" in m or "timed out" in m or "connection" in m or "network" in m:
        return "TIMEOUT_NETWORK"
    if "tool出力が不正" in msg or "keys=" in m:
        return "TOOL_OUTPUT_INVALID"
    if "reference_url" in m or "url fetch" in m or "fetch_page_text" in m or "参考情報" in msg:
        return "URL_FETCH_FAILED"
    if "csv" in m or "カラム" in msg or "utf-8" in m:
        return "CSV_INVALID"
    if "database is locked" in m or "db locked" in m or "sqlite busy" in m:
        return "DB_LOCKED"
    return "UNKNOWN"


def to_user_message(e: Exception, error_id: str) -> str:
    code = to_error_code(e)
    templates = {
        "QUOTA": "使用上限に達しました。管理者にお問い合わせください。",
        "API_AUTH": "設定に問題があります。管理者にお問い合わせください。",
        "RATE_CREDIT": "ただいま混み合っています。時間をおいて再度お試しください。",
        "TIMEOUT_NETWORK": "通信に失敗しました。時間をおいて再度お試しください。",
        "TOOL_OUTPUT_INVALID": "生成に失敗しました。時間をおいて再度お試しください。",
        "URL_FETCH_FAILED": "参考情報の取得に失敗しました。URLを見直して再度お試しください。",
        "CSV_INVALID": "CSVの形式に問題があります。ファイルを確認してください。",
        "DB_LOCKED": "一時的に処理できません。時間をおいて再度お試しください。",
        "UNKNOWN": "処理に失敗しました。時間をおいて再度お試しください。",
    }
    return f"{templates.get(code, templates['UNKNOWN'])}（エラーID: {error_id}）"


def _mask_text(text: str) -> str:
    if not text:
        return text
    masked = text
    patterns = [
        (r"sk-ant-[A-Za-z0-9\-_]+", "sk-ant-***"),
        (r"(?i)(api[_-]?key\s*[:=]\s*)([^\s,;]+)", r"\1***"),
        (r"(?i)(authorization\s*[:=]\s*bearer\s+)([^\s,;]+)", r"\1***"),
        (r"(?i)(bearer\s+)([^\s,;]+)", r"\1***"),
        (r"(?i)(token\s*[:=]\s*)([^\s,;]+)", r"\1***"),
    ]
    for p, r in patterns:
        masked = re.sub(p, r, masked)
    return masked


def _mask_obj(v: Any) -> Any:
    if isinstance(v, str):
        return _mask_text(v)
    if isinstance(v, dict):
        return {k: _mask_obj(val) for k, val in v.items()}
    if isinstance(v, list):
        return [_mask_obj(x) for x in v]
    if isinstance(v, tuple):
        return tuple(_mask_obj(x) for x in v)
    return v


def log_exception(app_logger, e: Exception, error_id: str, context: dict) -> None:
    safe_context = _mask_obj(context or {})
    safe_message = _mask_text(str(e or ""))
    app_logger.exception(
        "error_id=%s code=%s context=%s exception=%s",
        error_id,
        to_error_code(e),
        safe_context,
        safe_message,
    )
