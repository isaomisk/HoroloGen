# decisions

HoroloGen 開発の意思決定ログ（時系列）

このログは、チャットでの議論・試行錯誤・決定事項を「後から引き継げる形」に整理したものです。
日付は原則JST基準（ログ表示の都合で一部UTC混在の可能性あり）。

2026-01-XX（構想〜MVP設計初期）
D001: 正しい商品スペックは「1リファレンスにつき1つだけ」

目的: 時計は工業製品であり、同一リファレンスに複数の正規仕様が併存する状態は業務上許容できない。

決定:

(brand, reference) に対する正規仕様は 常に1つ

生成・検索・表示で参照する仕様は常に canonical spec

canonical優先順位: override > master(CSV) > empty

D002: CSVマスタ更新で、手入力（override）を自動上書きしない

目的: 現場判断の尊重／更新事故（意図しない上書き）を防止。

決定:

�）を壊さずに文体差を出�を分離

wriariant_id / tone指定で表現を制御

D007: MVPは「ダミー生成」で生成フローを先に完成

目的: LLM接続前にUI・運用・データフローを確定させる。

決定:

まず /staff/search にダミー生成を載せ、外部API無しでフロー完成

D008: 初期出力形式は「プレーンテキ GitHub連携は「MVPの一区切り後」に実施

目的: 初期開発中の思考分断を避ける。

決定:

ダミー生成まで完了を v0.1 として初回コミット

D011: HoroloGenは「生成AIツール」ではない

定義: 中核は 商品スペックの正規化と現場判断の保護。生成AIは補助機能。

キーメッセージ: 「正しさを壊さず、表現を広げる」

2026-01-17（生成履歴・再生成設計）
D012: 生成結果は「上書きせず必ず履歴として保存」

目的: 文章は試行錯誤の結果であり�ed_articles に新規INSERT

親子関係は将来拡張（payload等）で管理

D015: 生成・履歴・再生成を Staff 画面に統合

目的: 業務フローを分断しない。

決定:

/staff/search で 生成→結果→履歴→再生成 を1画面完結

2026-01-18〜2026-01-20（安全設計・表現制御・URL参照の前提）
D016: 「事故らない生成」を最優先（最終判断は必ずスタッフ）

決定:

自動採用・自動�L有無・editor_note等）で密度を変える

D019: editor_note（編集者メモ）を独立フィールドとして導入

目的: スタッフの経験・売り場感覚を反映。

決定:

remarks とは別に editor_note を持つ

introに必ず反映

主観は「私は〜と感じます」等の一人称で書く（事実ソース扱いにしない）

D020: 誇張・煽り表現をSYSTEMで禁止（自然表現は許可）

決定:

「必ず値上がり」「究極」等はNG

「完成度が高い」等の自然表現はOK

D021: URL利用は「信頼ドメイン × スタッフ確認」をte を facts から分離し、payloadトップレベルで渡す

目的: 主観がfacts（canonical_specs）を汚染しないようにする。

決定:

payload['facts'] には canonical_specs のみ

payload['editor_note'] を別フィールドで渡す

prompt側で [editor_note] セクションを明示し intro反映を強制

D025: editor_note カラム未整備の500はDBマイグレーションで解消

決定:

product_overrides に editor_note TEXT DEFAULT '' を追加

INSERT/UPSERT に editor_note を含める

実際に参照しているDB（例: /horologen.db）を特定し統一

D026: デバッグ用flashは最終的に削除しUIを汚さない

決定:

一時的な検証のみに使い、問題解決後は削除

D027: LLM tool出力はスキーマ厳密準拠、欠損はガード

決定:

intro_ン（ホワイトリスト）を取得ロジックに組み込む

決定:

is_allowed_reference_url(url) でドメイン判定

未許可は取得しない（空テキスト扱い）

D031: Wikipedia / note等のドメイン別ポリシーをSYSTEMに明記

決定:

Wikipedia: 年号・公式採用・行為など明確な事実は断定OK（解釈は距離）

note.com: 体験談としてのみ利用、数値/断定は禁止、主観表現に変換

その他未許可ソース: 無視

D032: 語り手は全トーンで「正規店スタッフ視点＋私は」に統一

目的: “私は禁止”などの混在で擬人化（時計が語aceholder を改善

決定:

「接客での実体験」＋「装着感・技術的ポイント」まで誘導文に含める

2026-01-30〜2026-01-31（CSVインポートの安全化・URL複数入力・UI整理）
D037: CSVインポートは「必須カラム一致＋余分カラムがあれば停止」

目的: 仕様外列混入による破壊的更新を防止。

決定:

missing があれば停止、extra があれば停止（エラー表示）

インポート結果（件数/エラー/差分サンプル等）を記録

D038: 参考URLはホワイトリスト方式（信頼ソースのみ取得）

決定:

TRUST_SOURCES に一致しないURLは取得しない

未許可URLは flash warning で通知

D039: 参考URLは最大3本入力、生成側は「採用URLを1本選ぶ」

目的: 本文が取れる確率を上�「URL処理の一本化」で防ぐ

決定:

reference_url の定義点を一箇所に固定し、古い断片ロジックを削除

D043: 履歴にもコピー導線を追加（方針合意）

決定（方針）:

履歴アイテムの intro/spec にもコピー操作を付ける

2026-02-01（baseline_ok 到達：URL本文が生成に効く状態を保証）
D044: 参考URL本文の取得を「生成に使う」ことをデバッグで保証

目的: “スペック寄りになる＝本文0文字”を確実に潰す。

決定:

per-URL の取得状況（allowed/status/method/chars/preview等）を収集

combined_reference_text を最大8000 chars連結し combined_reference_chars を可視化

UIで raw_urls_debug / combined_reference_chars / preview / per_url を表示

成果:

combined
将来復活は可能

2026-02-03（類似度の可視化・言い換え導線・テンプレ安定化）
D049: 参照URLは ref一致していなくても採用可（シリーズ/歴史用途）

決定:

ref一致は「優先採用のヒント」

一致がなくても最長本文等で採用し、理由として残す

D050: 類似度（%）をUI表示し、payload_jsonにも保存

目的: 参照元に近すぎるリスクの見える化。

決定:

similarity_percent と similarity_level(blue/yellow/red) を ref_meta に含める

DBは schema変更せず generated_articles.payload_json に保存

履歴表示でも payload_json から取り出して表示

D051: 「言い換え再生成（1回）」ボタンを用意（任意選択）

決定:

類似度の高�ewrite_parent_id=None

言い換え: rewrite_depth=src_depth+1, rewrite_parent_id=source_article_id

サーバ側ガード（二重防御）:

rewrite_parent_id = source_article_id の行が既に存在したらブロック

src_depth >= 1 を親にすることも禁止（孫リライト禁止）

UI方針:

rewrite_applied / rewrite_depth でボタン非表示 or 無効化

D054: 履歴表示に rewrite 状態を持たせる

決定:

_build_history_rows() で rewrite_depth / rewrite_parent_id / rewrite_applied を返し、UIと同条件で制御

D055: 物理保存 + Gitタグ運用を「改修前の儀式」にする

目�ザー向け文言に差し替え

詳細は app.logger.exception(...) でサーバログへ

D057: 月間生成回数上限を「プラン」で切り替える

目的: 公開後の無制限API消費を防止。

決定:

HOROLOGEN_PLAN=limited|unlimited

HOROLOGEN_MONTHLY_LIMIT=30（limited時）

monthly_generation_usage テーブルで used_count を月単位管理

生成/言い換え直前に consume_quota_or_block() を必ず通す

月キーはJST基準 YYYY-MM（_month_key_jst()）

2026-02-06〜2026-02-07（統合フェーズの事故・安定化）
D058: render_template() に同一キーを二重に渡す事故を防ぐ

背景: plan_mode 等が 明示引数 + **debug_defaults で重複し500になった。

決定:

debug_defaults は初期値用途に限定

同名キーを二重に渡さない（必要ならdebug_defaults側から削除）

2026-02-07（toで disabled 制御予定）

D061: 動作確認（画面確認・月間上限）

結果:

画面表示: OK

月間上限: OK（上限到達で表示・生成ブロック）

付記：安定点（タグ）と復旧ポリシー
D062: 安定点は「タグ」で明示し、復旧可能性を最優先する

例:

baseline_ok（URL fetch / combined_reference_chars>0）

rewrite_guard_try1_20260206_1245

以降、「rewrite guard + friendly errors + monthly quota」まで統合して安定化を進める

現在の原則（このログの要約）

正確性（facts）はシステムが守る：canonical一意、override保持、競合は検知のみ

人が決める領域を残す：競合解決、URL採用の確認、生成文の最終採用

生成は安全第一：誇張禁止、specsはテンプレ固定、tool欠損はガード

運用で壊れない：バックアップ＋タグ、JST表示、上限管

2026-02-08（エラーメッセージ統一の手動確認）
チェックリスト:
- /admin/upload でCSV未選択・不正CSV・必須カラム不足を発生させ、画面に日本語定型文 + エラーIDのみが表示されること
- /staff/search で生成エラー（APIキー未設定、通信失敗など）を発生させ、画面に生例外文字列が出ないこと
- 言い換えエラー時も同様に、画面は定型文 + エラーIDのみであること
- サーバーログでは error_id をキーに詳細追跡できること
