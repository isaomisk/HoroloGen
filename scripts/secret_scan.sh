#!/usr/bin/env bash
set -euo pipefail

PATTERN='ANTHROPIC_API_KEY|Bearer |Authorization:|api[_-]?key|client_secret|secret|token|password|passwd|sk-[A-Za-z0-9_-]{10,}'

TMP_ALL="$(mktemp)"
TMP_HITS="$(mktemp)"
trap 'rm -f "$TMP_ALL" "$TMP_HITS"' EXIT

rg -n "$PATTERN" . > "$TMP_ALL" || true

# Exclude documented key names / scanner internals / known safe identifiers.
awk '
  {
    if (index($0, "./README.md:") == 1) next
    if (index($0, "./docs/") == 1) next
    if (index($0, "./scripts/secret_scan.sh:") == 1) next
    if (index($0, "./.env.example:") == 1) next
    if ($0 ~ /max_tokens=/) next
    if ($0 ~ /api_key = os.getenv/) next
    if ($0 ~ /if not api_key or not cx/) next
    if ($0 ~ /"key": api_key/) next
    if ($0 ~ /missing_api_key_or_cx/) next
    if ($0 ~ /if not _api_key/) next
    if ($0 ~ /ANTHROPIC_API_KEY が未設定/) next
    if ($0 ~ /Anthropic\(api_key=_api_key\)/) next
    if ($0 ~ /app.secret_key = os.getenv/) next
    if ($0 ~ /anthropic_api_key/) next
    if ($0 ~ /\(\?i\)\(token\\s\*\[:=\]\\s\*\)/) next
    print
  }
' "$TMP_ALL" > "$TMP_HITS"

if [[ -s "$TMP_HITS" ]]; then
  cat "$TMP_HITS"
  echo "[NG] Potential secret-related strings found."
  exit 1
fi

echo "[OK] No potential secret-related strings found."
exit 0
