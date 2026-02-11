# HoroloGen（Horologen）

時計（ブランド×リファレンス）ごとの **商品紹介文（intro_text）** と **スペック文（specs_text）** を自動生成する、スタッフ向け社内ツールです。  
商品マスタ（canonical specs）をDBで管理し、必要に応じてオーバーライド（上書き）を行い、スタッフ所感（editor_note）も生成文に反映します。

生成には Anthropic Claude を利用し、参考URL（ホワイトリスト制）から本文を取得して文脈補助に使います。ただし **数値・仕様は canonical specs が最優先**です。

---

## 対象ユーザー
- 正規時計店のスタッフ（商品ページの紹介文作成、店頭対応の補助）
- 管理者（商品マスタCSV更新、運用）

---

## コア機能

### 1) 商品マスタ管理（Admin）
- CSVアップロードで `master_products` を一括更新
- 必須カラム検証（不足/余計なカラムがある場合は停止）
- 更新差分の検知（changed_count）
- オーバーライド競合の検知（override_conflict_count）
- アップロード履歴を `master_uploads` に保存（差分サンプル含む）

### 2) 商品検索・オーバーライド（Staff）
- brand/reference で検索
- master + override を合成して **canonical specs** を表示
- override の保存・解除
- `editor_note` を保存（生成文章に必ず反映）

### 3) 記事生成（LLM）
- `intro_text` と `specs_text` を生成（JSON固定出力）
- 参考URL（最大3本）本文抽出（ホワイトリストのみ取得）
- ref一致（リファレンス一致）優先で採用URLを決定
- 煽り文句BAN（禁止フレーズ検出）
- 類似度チェック（reference本文との n-gram Jaccard）

### 4) 言い換え（最大1回）
- 生成結果に対し **言い換え再生成は最大1回**
- サーバ側ガード：`rewrite_parent_id` で二回目を禁止
- UIでも言い換え済みの場合は非表示/無効化

### 5) 公開運用を見据えた安全設計
- 例外をサーバ側で握り、**ユーザー向け文言へ差し替え**
- ログには元の詳細を `logger.exception()` で保存
- 月間生成上限（サービス全体）
  - `limited`：月 `HOROLOGEN_MONTHLY_LIMIT` 回（デフォルト30）
  - `unlimited`：無制限

---

## 技術スタック
- Backend: Flask
- DB: SQLite
- Template: Jinja2
- LLM: Anthropic Claude（tools / JSON固定）
- URL本文取得: requests + BeautifulSoup（ドメインホワイトリスト）

---

## 画面（ローカル）
- Admin（CSVアップロード）: `http://127.0.0.1:5000/admin/upload`
- Staff（検索/生成/言い換え）: `http://127.0.0.1:5000/staff/search`

---

## ディレクトリ構成（例）

HoroloGen/
app.py
models.py
llm_client.py
url_discovery.py
horologen.db # ローカルSQLite（環境でパス固定の可能性あり）
templates/
base.html
admin.html
search.html
uploads/ # CSVアップロード用
backups/ # 手動バックアップ用（運用）
venv/ # ローカル環境


> ※あなたの環境では DB_PATH がローカル固定（例: /Users/misaki/...）になっている場合があります。将来的には環境変数化推奨。

---

## 環境変数

### 必須
- `ANTHROPIC_API_KEY`  
  Anthropic APIキー（未設定の場合、起動/生成で失敗します）

### 任意（LLM）
- `HOROLOGEN_CLAUDE_MODEL`  
  デフォルト: `claude-sonnet-4-5`

### 任意（Webサービス基盤）
- `DATABASE_URL`  
  本番想定: `postgresql://user:pass@host:5432/dbname`  
  未設定時はローカル `horologen.db`（SQLite）へフォールバック
- `SECRET_KEY`  
  セッション用。未設定時は `HOROLOGEN_SECRET_KEY` を使用

### 任意（プラン/上限）
- `HOROLOGEN_PLAN`  
  `limited` / `unlimited`（デフォルト: `limited`）
- `HOROLOGEN_MONTHLY_LIMIT`  
  `limited` 時の月間上限（デフォルト: `30`）

---

## セットアップ

### 1) 仮想環境
```bash
python -m venv venv
source venv/bin/activate
2) 依存インストール（例）
pip install flask requests beautifulsoup4 anthropic
requirements.txt を作る場合は pip freeze > requirements.txt 推奨。

3) 環境変数設定（例）
export ANTHROPIC_API_KEY="..."
export DATABASE_URL="postgresql://user:pass@host:5432/dbname"
export SECRET_KEY="replace-with-strong-secret"
export HOROLOGEN_CLAUDE_MODEL="claude-sonnet-4-5"
export HOROLOGEN_PLAN="limited"
export HOROLOGEN_MONTHLY_LIMIT="30"
4) 起動
python app.py

## 認証基盤（最小）動作確認

```bash
# DBマイグレーション
export DATABASE_URL="postgresql://user:pass@host:5432/dbname"
alembic upgrade head

# テストユーザー作成（例）
psql "$DATABASE_URL" -c "INSERT INTO tenants (name, plan) VALUES ('Demo Tenant','A') RETURNING id;"
psql "$DATABASE_URL" -c "INSERT INTO users (tenant_id, email, role, is_active) VALUES (1, 'staff@example.com', 'tenant_staff', true) ON CONFLICT (email) DO NOTHING;"

# アプリ起動
python app.py

# ログインURL発行（常に同じレスポンス）
curl -X POST -d "email=staff@example.com" http://127.0.0.1:5000/auth/request
```

サーバーログに `[MAGIC_LINK] http://127.0.0.1:5000/auth/verify?token=...` が出るので、開くと `/staff/search` へ遷移します。
DB（SQLite）概要
主なテーブル
master_products
商品マスタ（brand, reference がユニーク）

product_overrides
オーバーライド（editor_note含む）

master_uploads
CSVアップロード履歴（差分やエラーも保存）

generated_articles
生成履歴（intro/specs/payload_json）

rewrite_depth（0=通常生成 / 1=言い換え後）

rewrite_parent_id（親となる生成履歴ID）

monthly_generation_usage

month_key（JSTの YYYY-MM）

used_count

月間カウントの仕様
生成・言い換えの直前に consume_quota_or_block(n=1) を呼びます

limited で上限超過ならブロックし、生成は実行しません

unlimited はカウントせず常に許可

LLM生成の設計
事実の優先順位（重要）
canonical_specs（master + override の合成）

remarks（確認済みの事実）

reference_url 本文

仕様値（数値など）は canonical_specsのみを採用

reference URLは背景補助にのみ使用（文章コピーは禁止）

reference URL の制限
ホワイトリスト（TRUST_SOURCES）に含まれるドメインのみ取得

最大3本

ref一致（型番一致）優先で採用URLを決定

tool出力の安定化（keys=[] input={} 対策）
原則: tools の tool_use を拾う

tool_useが無い場合:

message.text から JSON抽出

最終手段として tools無しで「JSONのみ出力」で再試行

言い換え（最大1回）の仕様
サーバ側ガード
generated_articles を参照し、同じ rewrite_parent_id が既に存在する場合はブロック

さらに rewrite_depth>=1 の履歴を親にして言い換えるのも禁止（多段防止）

UI側
rewrite_depth==0 の時だけボタン表示

言い換え済みの場合「再度の言い換えは不可」を表示

追加改善案: 生成結果表示中はトーン・チェックボックス・URL入力もロックする（運用ミス防止）

エラーハンドリング方針
ユーザーに見せる文言
APIクレジット不足

レート制限

認証エラー

タイムアウト/通信エラー
などを humanize_llm_error() でまとめて差し替えます。

ログ
app.logger.exception(...) で詳細をサーバログに残します（管理者のみ確認）

運用メモ
1) DBバックアップ
horologen.db を定期的に backups/ にコピーする運用推奨

例:

cp horologen.db backups/2026-02-07_0100_stable/horologen.db
2) 本番化で追加したいこと（TODO）
認証（admin/staff分離）

ユーザー単位の月間上限（現状はサービス全体）

DBパス/secret_keyの環境変数化

CSRF対策、レート制限

生成ログの整理（request_id、失敗理由の分類）

ライセンス
社内利用想定（未設定）
