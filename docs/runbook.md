# Runbook

## 公開前チェック（秘匿）

- Push前に `./scripts/secret_scan.sh` を実行する。
- `.env` はローカル運用のみとし、共有が必要な設定キーは `.env.example` を使う。
- GitHub Push Protection に引っかかった場合は、秘匿値を除去して再コミットしてから再度 push する。
- 本番環境では `HOROLOGEN_SECRET_KEY` を必ず設定する（未設定運用は不可）。
- Basic認証やセッションを扱うため、本番公開は HTTPS 前提で運用する。
