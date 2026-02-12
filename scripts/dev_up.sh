#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT_DIR"

if ! command -v docker >/dev/null 2>&1; then
  echo "[dev_up] docker が見つかりません" >&2
  exit 1
fi

if ! docker compose version >/dev/null 2>&1; then
  echo "[dev_up] docker compose が使えません" >&2
  exit 1
fi

if [[ -z "${DATABASE_URL:-}" ]]; then
  export DATABASE_URL="postgresql://postgres:postgres@127.0.0.1:5432/horologen"
  echo "[dev_up] DATABASE_URL is not set. Using default: $DATABASE_URL"
fi

echo "[dev_up] starting postgres..."
docker compose up -d db

echo "[dev_up] waiting for db health..."
for i in {1..60}; do
  status="$(docker inspect --format '{{if .State.Health}}{{.State.Health.Status}}{{else}}{{.State.Status}}{{end}}' horologen-db 2>/dev/null || true)"
  if [[ "$status" == "healthy" || "$status" == "running" ]]; then
    if docker compose exec -T db pg_isready -U postgres -d horologen >/dev/null 2>&1; then
      echo "[dev_up] db is ready"
      break
    fi
  fi
  if [[ "$i" -eq 60 ]]; then
    echo "[dev_up] db health check timeout" >&2
    docker compose ps
    exit 1
  fi
  sleep 1
done

echo "[dev_up] running migrations..."
alembic upgrade head

echo "[dev_up] seeding dev data..."
python scripts/seed_dev.py

echo "[dev_up] done"
