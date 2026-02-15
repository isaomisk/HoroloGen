#!/usr/bin/env python3
"""Prod smoke checks for HoroloGen public release.

Checks:
- /auth/login => 200
- /auth/request => 404
- /staff/references?brand=TESTBRAND => 200 (10 times)
"""

import os
import sys
import urllib.error
import urllib.parse
import urllib.request

EXIT_FAIL = 2
TIMEOUT_SEC = 10


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def _base_url_from_env() -> str:
    raw = (os.getenv("APP_BASE_URL") or "").strip()
    if not raw:
        raise RuntimeError("APP_BASE_URL が未設定です。例: APP_BASE_URL=\"https://<prod-domain>\"")
    parsed = urllib.parse.urlparse(raw)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise RuntimeError("APP_BASE_URL は http(s)://<host> 形式で指定してください。")
    return raw.rstrip("/")


def _build_opener() -> urllib.request.OpenerDirector:
    return urllib.request.build_opener(NoRedirect)


def _fetch_status(opener: urllib.request.OpenerDirector, base_url: str, path: str) -> int:
    url = f"{base_url}{path}"
    req = urllib.request.Request(url=url, method="GET")
    try:
        with opener.open(req, timeout=TIMEOUT_SEC) as resp:
            return int(getattr(resp, "status", resp.getcode()))
    except urllib.error.HTTPError as e:
        return int(e.code)
    except urllib.error.URLError as e:
        raise RuntimeError(f"request failed: {path} ({e.reason})") from e


def _assert_status(opener, base_url: str, path: str, expected: int) -> None:
    got = _fetch_status(opener, base_url, path)
    print(f"CHECK {path} -> {got}")
    if got != expected:
        raise RuntimeError(f"status mismatch: {path} expected={expected} got={got}")


def main() -> int:
    base_url = _base_url_from_env()
    opener = _build_opener()

    _assert_status(opener, base_url, "/auth/login", 200)
    _assert_status(opener, base_url, "/auth/request", 404)

    path = "/staff/references?brand=TESTBRAND"
    for i in range(1, 11):
        got = _fetch_status(opener, base_url, path)
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
