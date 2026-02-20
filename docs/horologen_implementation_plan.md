# HoroloGen 実装計画書
## 参考URL取得改善 + トーンプロファイル改善 + 盗用リスク低減

作成日: 2026-02-19
ステータス: 設計完了 → 実装準備

---

## ■ 全体サマリー

今回の改善は大きく3つの領域にまたがる。

| 領域 | 概要 | 対象ファイル |
|---|---|---|
| A. 参考URL取得の改善 | 失敗時フォールバック + 英語記事自動補完 | url_discovery.py, app.py, llm_client.py |
| B. トーンプロファイルの改善 | 4トーンのinstructions具体化 | llm_client.py |
| C. ref_hit連動の定性情報ルール | ref_hit=falseの記事はスペック無視 | llm_client.py |

**依存関係：B と C は独立して実装可能。A は単独でも実装可能だが、B・Cと組み合わせて最大効果。**

---

## ■ 実装タスク一覧

### ===== 領域A：参考URL取得の改善 =====

#### A-1. 失敗URLのフォールバック検索（P1 最優先）
```
対象: url_discovery.py
内容: 新関数 fallback_search_from_failed_url() を追加

処理:
1. 失敗URLに対してHEADリクエストでページタイトル取得を試みる
2. 取得できない場合はURLパスからキーワード抽出
   例: /blog/cartier/tankamerican_mini
     → "カルティエ タンクアメリカン ミニ"
3. 抽出キーワードで Anthropic web_search tool で検索
4. ホワイトリスト通過 + 本文取得可能なURLを返す

入力: failed_url (str), max_urls=1 (int)
出力: list[str]  # 代替URL（0〜1件）
```

#### A-2. 英語ホワイトリストの追加（P2）
```
対象: llm_client.py の get_source_policy() 周辺
内容: 英語の時計メディアドメインをホワイトリストに追加

追加候補:
  hodinkee.com
  monochrome-watches.com
  watchtime.com
  watchesbysjx.com
  fratellowatches.com
  revolution.watch
  ablogtowatch.com
  thewatchbox.com（公式メディア部分のみ）

※ 英語ドメインは別リスト（EN_WHITELIST）として管理し、
  日本語ドメイン（JA_WHITELIST）と区別する。
  → lang判定にも使用するため。
```

#### A-3. 英語記事自動補完（P3）
```
対象: url_discovery.py
内容: 新関数 discover_english_urls() を追加

処理:
1. Anthropic web_search tool でクエリを順に実行:
   - "{brand} {reference} review"
   - "{brand} {reference} hands-on"
   - "{brand} {collection} review"（collectionがある場合）
2. EN_WHITELIST 通過URLのみ採用
3. max_urls件に達したら打ち切り

入力: brand (str), reference (str), collection (str|None),
      max_urls=1 (int)
出力: list[str]  # 英語記事URL（0〜1件）
```

#### A-4. app.py の生成処理フローを拡張（P3）
```
対象: app.py（生成処理部分、現在のStep 4〜6相当）
内容: フォールバック + 英語補完を組み込む

処理フロー:
1. ユーザー入力URL（最大3件）の本文取得を試みる
2. 失敗したURLがあれば fallback_search_from_failed_url() で代替
3. 日本語の確定URL件数に関わらず、
   discover_english_urls() で英語記事を1件追加
4. 確定リスト（最大4件）を生成ペイロードに渡す

※ URL入力が空欄の場合:
   → discover_reference_urls() で日本語最大2件
   → discover_english_urls() で英語1件
   → 合計最大3件 + canonical_specs で生成
```

#### A-5. 参考本文結合の上限変更（P3）
```
対象: llm_client.py（参考本文結合処理）
内容:
  - 各URL本文: 最大2500文字（変更なし）
  - 合計上限: 8000文字 → 10000文字に変更
  - 英語記事には lang="en" フラグを付与

プロンプト上の区別:
  各参考記事を渡す際に内部メタ情報を付与
  （LLMへのプロンプトに含める。ユーザーUIには非表示）

  --- 参考記事1（日本語 / ref_hit: true）---
  （本文）

  --- 参考記事2（日本語 / ref_hit: false）---
  （本文）

  --- 参考記事3（英語 / ref_hit: false）---
  （本文）
  ※この記事は英語です。定性情報のみを参考にし、
    翻訳調にせず自然な日本語で書いてください。
```

#### A-6. debug情報の拡張（P4）
```
対象: app.py（generated_articles保存部分）
内容: reference_urls_debug に以下を追加

各URLごとに:
  - url: str
  - lang: "ja" | "en"
  - source: "manual" | "fallback_ja" | "auto_ja" | "auto_en"
  - ref_hit: bool
  - fetch_status: "ok" | "fail"
  - char_count: int

※ adminページでのみ参照可能。ユーザーUIには非表示。
```

---

### ===== 領域B：トーンプロファイルの改善 =====

#### B-1. TONE_PROFILES定数の更新（P2）
```
対象: llm_client.py（TONE_PROFILESまたは同等の定数定義部分）
内容: tone_profiles_draft.md の改善版instructionsを反映

4トーン全てのinstructionsを更新:
  - luxury: 専門用語そのまま、比較推奨、「！」禁止、来店誘導禁止
  - casual_friendly: 噛み砕き説明必須、主観前面、来店誘導あり
  - magazine_story: 時系列展開、人物エピソード、「！」禁止
  - practical: 機能別構成、感情表現禁止、比喩禁止

※ 各トーンの「必ずやること」「禁止すること」「語彙の方向性」を
  現在のざっくりした説明から、具体的なルールリストに置き換える。

参照: /mnt/user-data/outputs/tone_profiles_draft.md
```

#### B-2. SYSTEM_BASEプロンプトの更新（P2）
```
対象: llm_client.py（build_system()関数）
内容: B-1のトーンルールが確実にLLMに渡るよう、
      systemプロンプトの構造を調整

確認ポイント:
  - 各トーンのinstructionsが十分な長さで渡されているか
  - 禁止ルールが明確に伝わる書き方になっているか
  - 文字数目安がURL有無に応じて正しく切り替わるか
```

#### B-3. 来店誘導に店名を含める（P3）
```
対象: llm_client.py（プロンプト生成部分）
内容: casual_friendly等で来店誘導する際に店舗名を使用するよう指示

方法:
  - payload に store_name を追加（app.py → llm_client.py）
  - プロンプトに「来店誘導の際は店舗名「{store_name}」を使用してください」を追加
  - store_name はテナント設定から取得
```

---

### ===== 領域C：ref_hit連動の定性情報ルール =====

#### C-1. ref_hit=falseの記事に対する定性情報限定ルール（P2）
```
対象: llm_client.py（build_user_prompt()関数）
内容: ref_hit=false の参考記事に対して、以下の指示をプロンプトに追加

「以下の参考記事には対象商品の型番が含まれていません。
 この記事からはデザインの印象、着用感、素材の質感、
 使い勝手などの定性的な情報のみを参考にしてください。
 サイズ、ムーブメント、価格などのスペック情報は
 一切参考にせず、確定スペックのみを使用してください。」

※ ref_hit=true の記事にはこの制限は付けない（現状通り）
```

---

## ■ 実装順序（推奨）

```
Phase 1（独立して着手可能、すぐ効果が出る）
  ├── B-1: トーンプロファイル更新
  ├── B-2: SYSTEM_BASEプロンプト更新
  └── C-1: ref_hit=false定性情報ルール

Phase 2（Phase 1と並行可能）
  ├── A-1: 失敗URLフォールバック検索
  └── A-2: 英語ホワイトリスト追加

Phase 3（A-1, A-2完了後）
  ├── A-3: 英語記事自動補完
  ├── A-4: app.py生成フロー拡張
  ├── A-5: 参考本文結合上限変更
  └── A-6: debug情報拡張

Phase 4（Phase 3完了後）
  └── B-3: 来店誘導の店名追加

Phase 5（全Phase完了後）
  └── 統合テスト
      同一商品で以下を比較:
      - 改善前 vs 改善後
      - 4トーン × URL有/無 × スタッフ追加入力有/無
      - 英語記事あり vs なし
      - 類似度チェック結果の確認
```

---

## ■ テスト計画

### 生成テスト用の商品候補

| 商品 | 特徴 | テスト目的 |
|---|---|---|
| Harry Winston AVCQHM16RR017 | 日本語レビューほぼなし | 英語記事補完の効果確認 |
| Omega Speedmaster 310.30.42.50.01.001 | 日本語記事豊富 | 日本語3件+英語1件の品質確認 |
| Cartier Panthère Mini WSPN0019 | 正規店ブログ多数 | casual_friendlyトーンの品質確認 |
| Grand Seiko SBGW291 | 日英両方記事あり | ref_hit有無の動作確認 |

### 確認項目

- [ ] 各トーンのルール遵守（必ずやること/禁止すること）
- [ ] BANNED_PHRASES非使用
- [ ] canonical_specsのスペック正確性
- [ ] ref_hit=falseの記事からスペック混入がないこと
- [ ] 英語記事の定性情報が自然な日本語で反映されていること
- [ ] 類似度が日本語参考記事に対して35%未満であること
- [ ] 文字数が目標範囲内であること
- [ ] debug情報にsource, lang, ref_hitが正しく記録されていること
- [ ] スタッフ追加入力がintro_textに自然統合されていること

---

## ■ 変更ファイル一覧

| ファイル | 変更内容 | Phase |
|---|---|---|
| url_discovery.py | fallback_search_from_failed_url() 追加 | 2 |
| url_discovery.py | discover_english_urls() 追加 | 3 |
| llm_client.py | TONE_PROFILES更新 | 1 |
| llm_client.py | build_system() 更新 | 1 |
| llm_client.py | build_user_prompt() にref_hit定性情報ルール追加 | 1 |
| llm_client.py | get_source_policy() に英語ホワイトリスト追加 | 2 |
| llm_client.py | 参考本文結合上限 8000→10000 | 3 |
| llm_client.py | 英語記事プロンプト指示追加 | 3 |
| llm_client.py | 来店誘導の店名パラメータ対応 | 4 |
| app.py | 生成処理にフォールバック+英語補完を追加 | 3 |
| app.py | debug情報拡張 | 3 |
| app.py | store_name をpayloadに追加 | 4 |

---

## ■ コスト影響

| 項目 | 現状 | 改善後 | 差分 |
|---|---|---|---|
| 参考本文上限 | 8000文字 | 10000文字 | +2000文字 |
| 入力トークン増 | - | 約+1000トークン/生成 | - |
| 月間コスト増（30本） | - | 約13円/月 | 無視可能 |
| Google CSE API呼出 | 現状通り | フォールバック時+1〜2回 | 微増 |

---

## ■ この計画書の使い方

**Codexに渡す場合:**
  Phase単位で指示。例：
  「Phase 1のB-1, B-2, C-1を実装してください。
   対象ファイルはllm_client.py。
   tone_profiles_draft.mdの内容を参照して
   TONE_PROFILESを更新してください。」

**Cursorで自分で実装する場合:**
  各タスクの「対象」「内容」「処理」をそのまま実装指示として使用。
  不明点があればこのチャットで確認。

**Claude Codeに渡す場合:**
  この計画書全体 + 対象ファイルのコードを渡して
  Phase単位で実装を依頼。
