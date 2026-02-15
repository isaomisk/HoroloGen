# AGENTS.md

## Working Assumptions (HoroloGen)

- ユーザーは今回が初めての開発。コード編集・張り替えはすべてCodexが行う。
- ユーザーは最終チェックのみを担当する（危険操作以外の yes/no は常に yes）。
- 破壊操作は禁止（`rm -rf`, `DROP`, `TRUNCATE`, `git reset --hard`, `git push --force`, `rebase` など）。
- 秘密情報（URL/キー/トークン）をログ・コミット・ドキュメントに書かない。
- 変更提示は「原因→最小修正→検証手順」でまとめる。
- staging/prod では `DATABASE_URL` と `SECRET_KEY` の取り違え事故を最優先で防ぐ。

## Operational Notes

- 本番運用手順の正本は `docs/RUNBOOK_PROD.md` を参照する。
- データ確認は `scripts/check_env_data.py` を使う（`scripts/check_staging_data.py` は後方互換）。
- Render の UI 操作は人間が実施し、Codex は指示文とリポジトリ変更で支援する。
