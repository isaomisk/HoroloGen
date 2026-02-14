# Runbook

公開運用（Render staging/prod）の手順は `docs/release-runbook.md` を参照してください。
prod公開の統合手順は `docs/RUNBOOK_PROD.md` を参照してください。

## 月間上限の運用（生成回数）

- 設定値:
- `HOROLOGEN_PLAN=limited` のとき月間上限を適用する。
- `HOROLOGEN_PLAN=unlimited` のとき上限は適用しない。
- `HOROLOGEN_MONTHLY_LIMIT` で上限回数を設定する（例: `30`）。
- カウント仕様:
- 生成と、言い換え（再生成）はそれぞれ 1 回として加算される。
- 上限チェックは LLM 呼び出し前に実行され、超過時は生成処理を止める。
- DB確認方法（SQLite）:
- `monthly_generation_usage` テーブルの `month_key`（`YYYY-MM`）と `used_count` を確認する。
- 例: `sqlite3 horologen.db "SELECT month_key, used_count FROM monthly_generation_usage ORDER BY month_key DESC LIMIT 12;"`
- 上限到達時の画面挙動:
- ユーザーには短い日本語メッセージ + エラーIDのみ表示される。
- 詳細原因はサーバーログの同じエラーIDで追跡する。

## CSV更新手順（`/admin/upload`）

- 事前確認:
- 管理画面にアクセスできること（公開時は認証必須）。
- CSVヘッダーがアプリ要件の必須カラムと一致していること。
- アップロード手順:
- `/admin/upload` を開く。
- CSVファイルを選択してアップロードする。
- 完了メッセージと件数（追加/更新/失敗）を確認する。
- 失敗時チェック:
- 文字コードが UTF-8 か。
- 必須カラムの不足・余剰カラムがないか。
- 取り込み対象データに空値や想定外フォーマットがないか。
- DBロック（`database is locked`）が発生していないか。
- 差分確認の見方:
- 取り込み前後で件数を比較する（`master_products`）。
- 例: `sqlite3 horologen.db "SELECT brand, COUNT(*) FROM master_products GROUP BY brand ORDER BY brand;"`
- 特定ブランド/リファレンスの存在確認を行う。
- 例: `sqlite3 horologen.db "SELECT brand, reference FROM master_products WHERE brand='omega' ORDER BY reference LIMIT 20;"`

## 障害時の切り分け（エラーID起点）

- 基本方針:
- 画面のエラーIDを必ず控える。
- ログ内の同じエラーIDを検索して詳細スタックを確認する。
- よくある原因:
- APIキー未設定・認証不備（`ANTHROPIC_API_KEY` など）。
- レート制限・クレジット不足。
- タイムアウト・通信失敗。
- 参考URL取得失敗（URL不正、取得先エラー、抽出失敗）。
- SQLiteロック（`database is locked`）。
- 1次対応:
- 環境変数設定を確認し、必要なら再設定する。
- 時間をおいて再試行し、同じエラーID系統が続くか確認する。
- URL入力値を見直し、アクセス可能なページか確認する。
- DBアクセス集中を避けて再実行する。

## 管理画面アクセス方針

- 管理画面（`/admin/*`）は開発元・販売元の運用担当のみ利用する。
- 公開環境では管理画面に認証を必須化する（未認証公開は禁止）。
- 管理操作・認証情報を扱うため、公開時は HTTPS 前提で運用する。
- 共有端末でのログイン状態放置を避け、作業後は必ずセッションを終了する。

## 公開前チェック（秘匿）

- Push前に `./scripts/secret_scan.sh` を実行する。
- `.env` はローカル運用のみとし、共有が必要な設定キーは `.env.example` を使う。
- GitHub Push Protection に引っかかった場合は、秘匿値を除去して再コミットしてから再度 push する。
- Render の staging/prod では `SECRET_KEY` を必ず設定する（未設定運用は不可）。
- Basic認証やセッションを扱うため、本番公開は HTTPS 前提で運用する。


## Git: `fatal: bad object refs/heads/...`（壊れref）の復旧

- 症状:
- `git fetch` / `git pull` が以下のようなエラーで止まる:
- `fatal: bad object refs/heads/<branch> 2`
- `error: <remote> did not send all necessary objects`
- 原因（よくあるパターン）:
- `.git/refs/heads/` 配下に、ブランチ名として不正な参照ファイルが紛れ込んでいる。
- 例: `stable-before-admin 2` のように「スペース＋数字」が付いたファイル
- 復旧手順（sudo禁止）:
- 1) 現状確認:
- `ls -la .git/refs/heads`
- 2) 見覚えのない参照（スペース入り等）があれば中身確認（任意）:
- `cat ".git/refs/heads/<壊れた名前>"`
- 3) 壊れrefを削除（必ずダブルクォートで囲む）:
- `rm -f ".git/refs/heads/<壊れた名前>"`
- 念のためGit経由でも削除:
- `git update-ref -d "refs/heads/<壊れた名前>" 2>/dev/null || true`
- 4) 参照の再パックと再取得:
- `rm -f .git/packed-refs.lock`
- `git pack-refs --all --prune`
- `git fetch --prune origin`
- `git pull`
- 5) 解消確認:
- `git status --short`
- `git log --oneline -n 5`
- 補足:
- `.git` 配下の権限を `sudo` / `chown` で変更すると別事故になりやすいので、まずは上記の“壊れrefのピンポイント削除”で対応する。
