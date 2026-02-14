# HoroloGen Prod Build & Release Runbook

この1ページで、`stagingで確立した手順をprodへ再現` するための最小手順をまとめます。
値そのもの（URL/キー/トークン）は貼らず、Render Dashboard の Environment で管理してください。

## 1) Render構成（作るもの）

- [ ] Render Postgres（prod用）
- [ ] Render Web Service（prod用）
- [ ] （推奨）staging/prod を別サービスで分離

## 2) Deploy設定（staging/prod共通）

- [ ] Build Command: `pip install -r requirements.txt`
- [ ] Start Command: `gunicorn app:app`
- [ ] Pre-deploy Command: `alembic upgrade head`
- [ ] Deployログで migration 成功を確認
- [ ] 補足: `gunicorn` の workers / timeout 等の引数は環境に合わせて調整する

## 3) 環境変数（prod最小セット）

- [ ] `APP_ENV=prod`（stagingは `APP_ENV=staging`）
- [ ] `DATABASE_URL=<RenderのPostgres接続URL>`
- [ ] `SECRET_KEY=<十分長いランダム文字列>`
- [ ] `DEBUG_AUTH_LINKS=0`（または未設定）
- [ ] `ANTHROPIC_API_KEY=<必要時のみ設定>`

補足:
- `APP_ENV != "dev"` で `SECRET_KEY/HOROLOGEN_SECRET_KEY/FLASK_SECRET_KEY` が空なら、アプリは起動失敗（仕様）。
- 運用は `SECRET_KEY` に統一する。

### SECRET_KEY 生成例（値は記録しない）

```bash
python -c "import secrets; print(secrets.token_urlsafe(64))"
```

## 4) データ投入Runbook（staging/prod共通）

### 4-1. 接続先確認

```bash
export DATABASE_URL="<RenderのDATABASE_URL>"
python scripts/check_env_data.py
```

### 4-2. （任意）tenants/users 初期投入が必要な場合のみ

```bash
# 必要に応じて実行（dev用seedをstaging/prodで常用しない）
# python scripts/seed_dev.py
```

### 4-3. 最小商品seed（0件回避の最短）

```bash
python scripts/seed_staging_min.py
python scripts/check_env_data.py
```

### 4-4. SQLite から master_products を tenant指定で投入（冪等）

```bash
# 例: tenant_id=2 へ投入
TENANT_ID=2 python scripts/import_master_products_from_sqlite.py

# 必要ならSQLiteパス指定
TENANT_ID=2 SQLITE_DB_PATH="/path/to/horologen.db" python scripts/import_master_products_from_sqlite.py
```

投入スクリプトの安全性:
- `ON CONFLICT (tenant_id, brand, reference) DO NOTHING` で既存はスキップ
- 破壊的更新をしない（同コマンド再実行可）

## 5) 公開前チェックリスト（P0）

- [ ] `platform-admin` で `/auth/login` ログインできる
- [ ] `staff-a` で `/auth/login` ログインできる
- [ ] `/staff/references?brand=TESTBRAND` が `count:1` を返す
- [ ] `/staff/references?brand=TESTBRAND` を10回リロードして全部 `200`
- [ ] `/staff/search` で `REF001` が候補表示される
- [ ] staff で `/admin/*` 直アクセスが `403`
- [ ] `/auth/request` は `APP_ENV != dev` で `404`（5秒後 `/auth/login` へ遷移）
- [ ] 管理画面でテナント作成・staff作成・有効/無効化が運用できる
- [ ] `tenant_staff` 上限5件（active=trueのみカウント）が効いている

## 6) 事故ポイントの明文化

### 6-1. 「0件」事故について

`/staff/references` と `/staff/search` は `tenant_id` スコープの `master_products` を参照する仕様。
seed（tenants/users中心）のみでは `master_products` が十分に入らず、候補が0件になることがある。
これは障害ではなく、データ未投入の状態。

### 6-2. 「302揺れ」再発防止

`APP_ENV != "dev"` では `SECRET_KEY` 必須。未設定だと起動失敗にすることで、
再起動ごとにセッション署名が変わる事故を防ぐ。

## 7) 安全運用ルール（破壊禁止）

- DB削除、全消し、reset系は実施しない
- 秘密情報をコミット/ログ出力しない
- 復旧時は「migration再実行 → 冪等seed/import再実行」の順で対処

## 8) （任意）Sentry導入ガイド

- `SENTRY_DSN` を環境変数で設定（値はドキュメントに書かない）
- `environment` タグに `staging` / `prod` を付与
- PII除外方針:
  - email / token / cookie / Authorization ヘッダは送信しない
  - request body は原則マスク
- 初期はエラーイベントのみ送信し、トランザクション監視は必要時に段階導入

## 9) （任意）バックアップ/PITR 運用前提

- Render Postgres のバックアップと PITR が有効かを事前確認
- 復旧演習チェック項目:
  - いつの時点まで戻せるか（RPO）
  - どのくらいで復旧できるか（RTO）
  - 復旧後に `alembic current` と `scripts/check_env_data.py` で整合確認できるか
