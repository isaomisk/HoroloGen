#!/usr/bin/env python3
"""Backward-compatible wrapper.

Deprecated: use scripts/check_env_data.py instead.
"""

from check_env_data import main


if __name__ == "__main__":
    print("[DEPRECATED] scripts/check_staging_data.py は将来廃止予定です。scripts/check_env_data.py を使ってください。")
    raise SystemExit(main())
