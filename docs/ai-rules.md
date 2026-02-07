AI向け開発ルール（HoroloGen / 現状コード準拠）
0) この文書が対象にする“現状の実体”

このプロジェクトは、以下の構成を前提とする（名称は実ファイルに合わせる）：

app.py（Flask本体：/admin/upload と /staff/search）

models.py（SQLite初期化・接続）

llm_client.py（Anthropicで記事生成：URL本文抽出 + Tool出力処理 + 類似度 + 言い換え）

url_discovery.py（参考URLの自動探索：discover_reference_urls()）

templates/search.html（スタッフ画面：検索・オーバーライド・生成・言い換え・履歴）

templates/admin.html（CSVアップロード画面）

DB: horologen.db

master_products

product_overrides（editor_note含む）

generated_articles（rewrite_depth, rewrite_parent_id含む）

monthly_generation_usage（month_key, used_count）

1) 絶対に壊してはいけない部分（Invariants）
1-1. 事実の優先順位（最重要 / llm_client.pyのSYSTEM規約）

優先順位は必ず：

canonical_specs（= master + override の合成。app.py内で canonical を作って payload['facts'] に入れる）

remarks（canonical内に入る備考）

reference_url 本文（URL抽出で得たテキスト）

禁止：

URL本文から数値・スペックを断定して specs_text に入れること

推測でスペックを補完すること

1-2. specs_text の形式（固定）

llm_client.py の _specs_text_from_canonical() で作るテンプレの形式を壊さない。

canonicalに存在する項目のみ

箇条書き（・ラベル：値）

ラベル+値のみ（評価・煽り・装飾禁止）

出力順は FIELD_LABELS_ORDER に従う

1-3. intro_text の語り手ルール（固定）

語り手は「正規時計店スタッフ」

ブランド・メーカーが喋る体裁は禁止

読者が喋る体裁は禁止

1-4. editor_note は必ず反映（重要）

payload['editor_note'] は、intro_text内に必ず反映。
未入力なら触れない。

1-5. 煽り禁止（BANNED_PHRASES）

llm_client.py の BANNED_PHRASES に触れる表現は 例外にして失敗扱いを維持する。

1-6. 言い換えは最大1回（UIだけでなくサーバ側で保証）
DBとロジックの前提

generated_articles.rewrite_depth

0: 通常生成

1: 言い換え後（最大1回）

generated_articles.rewrite_parent_id

言い換え元の generated_articles.id

不変条件

同じ rewrite_parent_id を持つ行が2つ以上作られないようにする

app.py の action == 'rewrite_once' で
SELECT 1 FROM generated_articles WHERE rewrite_parent_id = ? LIMIT 1
でブロックする（このガードは維持）

rewrite_depth>=1 の履歴を親にして再言い換えは禁止（維持）

1-7. 月間上限（クォータ）は LLM呼び出し前に消費

consume_quota_or_block(n=1) を LLM呼び出し前に必ず実行

monthly_generation_usage は サービス全体で共通カウント

競合防止に BEGIN IMMEDIATE を使う（現状方針維持）

2) 変更して良い部分／ダメな部分
2-1. 変更して良い（改善OK）

templates/search.html のUI/デザイン改善（配置・見た目・注意文の改善）

humanize_llm_error(e) の文言改善（ユーザー向けだけ）

app.logger.exception(...) のログ整備

URL本文抽出 fetch_page_text() の改善（ただしホワイトリストは維持）

Tool出力失敗時の保険強化（keys=[] input={} 対策）

CSVインポート周りのUX

2-2. 変更してはいけない（破壊変更NG）

上記 Invariants に違反する変更

specs_text のフォーマット破壊

editor_note を反映しない変更

TRUST_SOURCES 制限を外して任意URLを取りに行く変更

言い換え最大1回のサーバガード削除

クォータを LLM後に消費する変更（コスト事故につながる）

3) 実装時の優先順位（迷ったらこれ）

不変条件（Invariants）を守る

運用事故防止

API無限消費、二重送信、言い換え無限、URLの無制限取得、エラー詳細の露出

DB後方互換

例外時の安定運用

ユーザーには安全な文言 / ログには詳細

UI改善（ただし事故防止UIは維持）

パフォーマンス・リファクタ

4) 実装スタイル（このプロジェクトの“暗黙のルール”を明文化）
4-1. app.py（Flask）

render_template() に渡すキーワードは 重複禁止

**debug_defaults と個別引数で同じキーを2回渡すと500になる

例：plan_mode, combined_reference_chars が過去に衝突した

“生成→保存→表示”の流れは維持する

生成前に canonical を確定し、それを payload に入れる

LLM呼び出しは必ず try/except で囲み、

app.logger.exception("... failed: %s", e) でログを残し

flash(humanize_llm_error(e), 'error') でユーザー向け文言に変換する

4-2. llm_client.py（LLM呼び出し）

Tool出力が取れない（keys=[] input={}）ことは 普通に起きる前提

したがって _extract_once() は以下を必ず持つ（現状方針）：

toolsで取得 → _pick_tool_input()

tool_useが無い場合：_message_text() → _extract_json_object_from_text()

最終保険：tools無しで “JSONだけ” 返させて抽出

fetch_page_text() は抽出量を制限し、本文コピペを避ける前提を維持

4-3. models.py（DB）

既存テーブルに対するALTERは「存在しない場合だけ」

新テーブル追加はOK（ただし既存画面が壊れないように段階導入）

4-4. templates/search.html（スタッフUI）

生成結果が表示されている間は入力をロックする（事故防止）

トーンselect：ロック（変更不可）

チェックボックス類：ロック（変更不可）

参考URL入力：ロック（変更不可）

目的：生成結果を見ながらフォーム値が変わり、意図しない生成になる事故を防ぐ

5) “今の実装の前提”としての変数一覧（テンプレが期待するもの）

templates/search.html は最低限、以下を受け取る想定（不足でJinjaエラーになり得る）：

brands

brand, reference

canonical, overridden_fields, master, override

warnings, override_warning, import_conflict_warning

generated_intro_text, generated_specs_text

generation_tone, generation_include_brand_profile, generation_include_wearing_scenes, generation_reference_urls

selected_reference_url, selected_reference_reason

similarity_percent, similarity_level

saved_article_id, rewrite_depth

history（_build_history_rows() で整形されたもの）

debug系：combined_reference_chars, combined_reference_preview, reference_urls_debug, llm_client_file, raw_urls_debug

クォータ表示：plan_mode, monthly_limit, monthly_used, monthly_remaining, month_key

6) 手動テスト（最低限の確認リスト）

変更後は最低限これを壊していないこと：

/admin/upload が開く

/staff/search が開く（500が出ない）

検索 → canonical表示が出る

生成成功 → 履歴保存（rewrite_depth=0）

言い換え成功（rewrite_depth=1, rewrite_parent_idが入る）

同じ履歴から2回目の言い換えがブロックされる（サーバ側）

月間上限で生成/言い換えがブロックされる

LLMエラー時、画面に詳細が出ず、ログに詳細が残る

7) AIへの必須ルール（出力と説明）

説明は必ず日本語

初心者が貼れるように 「どのファイルのどの関数を丸ごと差し替えるか」 を明記

変更は最小単位で（関数単位 or ファイル単位）

「目的 → 影響範囲 → 貼り替えコード → 動作確認手順」を必ず書く