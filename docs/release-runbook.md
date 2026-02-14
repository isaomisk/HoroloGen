# Release Runbook (Render: staging/prod)

この手順書は、HoroloGen を Render の `staging` / `prod` に安全に反映するための最小運用をまとめたものです。

## 1. 環境変数一覧

値そのものは Render Dashboard の Environment で管理し、このドキュメントやログに貼らないこと。

### 共通（staging/prod）

- `DATABASE_URL`
  - Render Postgres 接続URL。
  - アプリ内部で SQLAlchemy 用に `postgresql+psycopg://` へ正規化される実装のため、環境変数は `postgresql://...` を基本とする。
- `SECRET_KEY`
  - Flask セッション署名キー。必須。Render ではこの名前に統一して設定する。
- `ANTHROPIC_API_KEY`
  - 記事生成に必要。未設定時は生成のみ失敗する。
- `HOROLOGEN_PLAN`
  - `limited` または `unlimited`。
- `HOROLOGEN_MONTHLY_LIMIT`
  - `limited` 時の月間上限（例: `30`）。
- `DEBUG_AUTH_LINKS`
  - 通常は `0`（または未設定）。magic link運用は使わない。

### staging 推奨

- `FLASK_ENV=production`
- `DEBUG_AUTH_LINKS=0`
- 任意で運用確認向けに `HOROLOGEN_PLAN=limited`

### prod 推奨

- `FLASK_ENV=production`
- `DEBUG_AUTH_LINKS=0` 固定
- `SECRET_KEY` を staging と別値にする

## 2. DB 初期化 / seed / import

Render Shell（Web Service 側）で実行する想定。

### 2.1 migration

```bash
python -m alembic upgrade head
```

期待結果: エラーなく `head` まで到達する。

### 2.2 基本seed（users/tenants）

```bash
python scripts/seed_dev.py
```

補足: 既存ユーザーがある場合は冪等更新（重複作成しない）。

### 2.3 最小商品seed（stagingで画面確認したい場合）

```bash
python scripts/seed_staging_min.py
```

期待結果: `Tenant A` に `TESTBRAND / REF001 / price_jpy=123456` が投入される（冪等）。

### 2.4 SQLite から master_products 一括移行（必要時）

`horologen.db` が作業環境にある場合のみ実行。

```bash
# tenant 2（staff-a想定）
TENANT_ID=2 python scripts/import_master_products_from_sqlite.py

# tenant 3（staff-b想定, 任意）
TENANT_ID=3 python scripts/import_master_products_from_sqlite.py
```

期待結果: `(tenant_id, brand, reference)` 既存キーはスキップされ、破壊的更新をしない。

### 2.5 データ確認

```bash
python scripts/check_env_data.py
```

確認ポイント:

- tenants が存在する
- `staff-a@example.com` の `tenant_id` が想定通り
- `master_products` が tenant ごとに入っている
- `TESTBRAND / REF001` が参照できる

## 3. 動作確認（staging/prod 共通）

1. `platform-admin` でログインできる
2. `staff-a` でログインできる
3. `/staff/references?brand=TESTBRAND` が `count:1` を返す
4. `/staff/references?brand=TESTBRAND` を 10 回リロードして、すべて `200` を返す
5. `/staff/search` で `REF001` 選択時に `price_jpy=123456` が表示される
6. staff で `/admin/upload` 直アクセス時に拒否される（RBAC）
7. admin で staff パスワード再発行後、対象 staff は次回ログイン時にパスワード変更が強制される

## 4. ロールバック手順

破壊操作は禁止。以下の順で「アプリを戻す」か「DBを進め直す」。

### 4.1 アプリのみ切り戻し

1. Render Dashboard で直前の安定 Deploy を選んで Re-deploy
2. Application Logs で起動成功を確認
3. ログインと `/staff/search` 最低動作を再確認

### 4.2 migration 起因の障害時

1. まず `python -m alembic current` / `python -m alembic heads` で状態確認
2. 欠損テーブル起因なら、最新 migration を再実行:
   - `python -m alembic upgrade head`
3. データ不足起因なら seed/import を再実行（冪等スクリプトのみ）
4. `downgrade` はデータ影響を伴うため、実施前に運用判断を必須とする

## 5. 監視 / ログの見方（Render）

### 5.1 Render Dashboard

- Web Service:
  - `Logs` → Application Logs（アプリ例外・Flaskログ）
  - `Events` → Deploy 成否、起動失敗、再起動履歴
- Postgres:
  - 接続可否、メトリクス、ストレージ使用量

### 5.2 最低限見るべきログ

- `alembic upgrade head` の成功/失敗
- `UndefinedTable`, `NoSuchTableError`, `ModuleNotFoundError` の有無
- 認証失敗多発（ログインエラー偏り）
- 500 応答時のエラーID（画面表示）と Application Logs の突合

### 5.3 障害一次切り分け

1. 画面のエラーIDを控える
2. 同時刻の Application Logs で該当例外を確認
3. DB欠損なら migration/seed/import の順で復旧
4. RBAC/tenant 不整合なら users/tenants/master_products の整合を確認
