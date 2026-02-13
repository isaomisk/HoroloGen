# Development Quickstart (PostgreSQL)

このドキュメントは、認証/DB/画面の検証を最短で回すための手順です。

## 1) Python 仮想環境 (.venv311)

```bash
python3.11 -m venv .venv311
source .venv311/bin/activate
python -m pip install --upgrade pip
pip install -r requirements.txt
```

## 2) DATABASE_URL を設定

```bash
export DATABASE_URL="postgresql://postgres:postgres@127.0.0.1:5432/horologen"
```

## 3) Alembic migration 適用

```bash
alembic upgrade head
```

## 4) 開発用シード投入（2テナント + admin/staff）

```bash
python scripts/seed_dev.py
```

## 4.1) staging最小データ投入（必要時のみ）

`seed_dev.py` は認証用ユーザー中心のため、`master_products` が空の環境では staff 画面候補が出ません。  
Render Shell で以下を1回実行すると、`Tenant A` に `TESTBRAND / REF001 / price_jpy=123456` を冪等投入できます。

```bash
python scripts/seed_staging_min.py
```

投入前後の確認:

```bash
python scripts/check_staging_data.py
```

## 4.2) SQLite master_products を Postgres へ移行（tenant指定・冪等）

ローカル `horologen.db` の `master_products` を、指定テナントへ移行します。  
既存キー `(tenant_id, brand, reference)` は `DO NOTHING` でスキップするため、繰り返し実行できます。

```bash
# 例: staff-a 向け（tenant_id=2）へ投入
TENANT_ID=2 python scripts/import_master_products_from_sqlite.py

# 任意: staff-b 向け（tenant_id=3）へも投入
TENANT_ID=3 python scripts/import_master_products_from_sqlite.py
```

必要に応じて SQLite パスを変更:

```bash
TENANT_ID=2 SQLITE_DB_PATH=/path/to/horologen.db python scripts/import_master_products_from_sqlite.py
```

投入されるユーザー例:

- `platform-admin@example.com` (`platform_admin`, tenantなし)
- `staff-a@example.com` (`tenant_staff`, Tenant A)
- `staff-b@example.com` (`tenant_staff`, Tenant B)

## 5) サーバ起動

```bash
python app.py
```

`ANTHROPIC_API_KEY` が未設定でもサーバは起動できます。
ただし記事生成実行時は `ANTHROPIC_API_KEY が未設定です` で失敗します。

## 6) ログインURL（マジックリンク）確認

```bash
curl -X POST -d "email=staff-a@example.com" http://127.0.0.1:5000/auth/request
```

サーバログに `[MAGIC_LINK] http://127.0.0.1:5000/auth/verify?token=...` が出るので、そのURLをブラウザで開いてログインします。

## よくある失敗ポイント

- `0002` migration は PostgreSQL 前提です。SQLite では同じ手順で通りません。
- SQLite はスモーク用途のみ、実検証は PostgreSQL で行ってください。
- Git操作はローカル環境で実施してください（この手順書は実行手順のみ）。

## ワンコマンド実行（推奨）

`docker-compose.yml` と `scripts/dev_up.sh` がある前提で、以下1行で DB起動〜migration〜seed まで実行できます。

```bash
./scripts/dev_up.sh && python app.py
```

## Dockerトラブルシュート

```bash
docker compose ps
docker compose logs db --tail=200
docker ps --filter name=horologen-db
```
