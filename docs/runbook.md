# Runbook

## 公開前チェック（秘匿）

- Push前に `./scripts/secret_scan.sh` を実行する。
- `.env` はローカル運用のみとし、共有が必要な設定キーは `.env.example` を使う。
- GitHub Push Protection に引っかかった場合は、秘匿値を除去して再コミットしてから再度 push する。
