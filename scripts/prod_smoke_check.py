#!/usr/bin/env python3
"""Prod smoke checks for HoroloGen public release.

Checks:
- /auth/login => 200
- /auth/request => 404
- login with SMOKE_EMAIL/SMOKE_PASSWORD
- /staff/references?brand=TESTBRAND => 200 (10 times, after login)
"""

import os
import sys
from html.parser import HTMLParser
from urllib.parse import urlparse

import requests

EXIT_FAIL = 2
TIMEOUT_SEC = 10


class _HiddenInputParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.hidden_fields: dict[str, str] = {}

    def handle_starttag(self, tag: str, attrs):
        if tag.lower() != "input":
            return
        attr_map = {k.lower(): (v or "") for k, v in attrs}
        if attr_map.get("type", "").lower() != "hidden":
            return
        name = (attr_map.get("name") or "").strip()
        if not name:
            return
        self.hidden_fields[name] = attr_map.get("value", "")


def _require_env(key: str) -> str:
    raw = (os.getenv(key) or "").strip()
    if not raw:
        raise RuntimeError(f"{key} が未設定です。")
    return raw


def _base_url_from_env() -> str:
    raw = _require_env("APP_BASE_URL")
    parsed = urlparse(raw)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise RuntimeError("APP_BASE_URL は http(s)://<host> 形式で指定してください。")
    return raw.rstrip("/")


def _get_status(session: requests.Session, base_url: str, path: str) -> int:
    try:
        resp = session.get(f"{base_url}{path}", timeout=TIMEOUT_SEC, allow_redirects=False)
        return int(resp.status_code)
    except requests.RequestException as e:
        raise RuntimeError(f"request failed: {path}") from e


def _assert_status(session: requests.Session, base_url: str, path: str, expected: int) -> None:
    got = _get_status(session, base_url, path)
    print(f"CHECK {path} -> {got}")
    if got != expected:
        raise RuntimeError(f"status mismatch: {path} expected={expected} got={got}")


def _login(session: requests.Session, base_url: str, email: str, password: str) -> None:
    login_path = "/auth/login"
    try:
        login_get = session.get(f"{base_url}{login_path}", timeout=TIMEOUT_SEC, allow_redirects=False)
    except requests.RequestException as e:
        raise RuntimeError("request failed: /auth/login") from e
    print(f"CHECK {login_path} [GET] -> {login_get.status_code}")
    if login_get.status_code != 200:
        raise RuntimeError(f"status mismatch: /auth/login expected=200 got={login_get.status_code}")

    parser = _HiddenInputParser()
    parser.feed(login_get.text or "")
    form_data = dict(parser.hidden_fields)
    form_data["email"] = email
    form_data["password"] = password

    try:
        login_post = session.post(
            f"{base_url}{login_path}",
            data=form_data,
            timeout=TIMEOUT_SEC,
            allow_redirects=False,
        )
    except requests.RequestException as e:
        raise RuntimeError("request failed: /auth/login (POST)") from e
    print(f"CHECK {login_path} [POST] -> {login_post.status_code}")
    if int(login_post.status_code) not in {302, 303}:
        raise RuntimeError(f"status mismatch: /auth/login POST expected=302/303 got={login_post.status_code}")


def main() -> int:
    base_url = _base_url_from_env()
    smoke_email = _require_env("SMOKE_EMAIL")
    smoke_password = _require_env("SMOKE_PASSWORD")
    session = requests.Session()

    _assert_status(session, base_url, "/auth/request", 404)
    _login(session, base_url, smoke_email, smoke_password)

    path = "/staff/references?brand=TESTBRAND"
    for i in range(1, 11):
        got = _get_status(session, base_url, path)
        print(f"CHECK {path} [{i}/10] -> {got}")
        if got != 200:
            raise RuntimeError(f"status mismatch: {path} run={i} expected=200 got={got}")

    print("OK: prod smoke checks passed")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except RuntimeError as e:
        print(f"[prod_smoke_check] {e}", file=sys.stderr)
        raise SystemExit(EXIT_FAIL)
