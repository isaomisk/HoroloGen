AI向け開発ルール（HoroloGen / 現状コード準拠）
0) この文書が対象にする“現状の実体”

このプロジェクトは、以下の構成を前提とする（名称は実ファイルに合わせる）：

app.py（Flask本体：/admin/upload と /staff/search）

models.py（SQLite初期化・接続）

llm_client.py（Anthropicで記事生成：URL本文抽