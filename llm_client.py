import json
import os
import re
import requests
from bs4 import BeautifulSoup
from anthropic import Anthropic

from urllib.parse import urlparse
from typing import Tuple, Optional, Dict, Any, List


# ----------------------------
# Anthropic client
# ----------------------------
MODEL = os.getenv("HOROLOGEN_CLAUDE_MODEL", "claude-sonnet-4-5")
_client: Optional[Anthropic] = None


def _get_client() -> Anthropic:
    global _client
    if _client is not None:
        return _client
    api_key = (os.getenv("ANTHROPIC_API_KEY") or "").strip()
    if not api_key:
        raise RuntimeError("ANTHROPIC_API_KEY が未設定です")
    _client = Anthropic(api_key=api_key)
    return _client


# ----------------------------
# Tool schema (固定JSON出力)
# ----------------------------
ARTICLE_TOOL = {
    "name": "return_article",
    "description": "時計商品紹介文とスペック文を返す。事実はcanonical_specsとremarksとreference_url本文の範囲のみ。",
    "input_schema": {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "intro_text": {"type": "string"},
            "specs_text": {"type": "string"},
        },
        "required": ["intro_text", "specs_text"],
    },
}


# ----------------------------
# SYSTEM: base + tone
# ----------------------------
SYSTEM_BASE = """あなたは正規時計店で使用される、商品説明文を作成する業務用アシスタントです。

【出力言語】
- 日本語のみ
- 固有名詞・型番・キャリバー名は原文表記を可とする

【出力物（厳守）】
- intro_text（商品紹介文）
- specs_text（商品スペック文）
上記2つのみを出力する。
前置き・注釈・見出し・余計な文章は禁止。

────────────────────
【語り手の定義（全トーン共通）】
────────────────────
- intro_text の語り手は「正規時計店のスタッフ（販売員・時計担当者）」である。
- 時計・ブランド・メーカーが語り手になる表現は禁止。
- 読者が語り手になる表現は禁止。
- 記事は必ず「店舗スタッフが商品を紹介している体裁」で書く。

────────────────────
【トーン別の文体ルール】
────────────────────

■ luxury（フォーマル・権威型）
- 文体：です・ます調（丁寧・格調高め）
- 語彙は抑制的で、専門店としての信頼感を重視する
- 技術説明・仕様解説では主語を極力省略する
- 一人称「私は」は以下の場合に限定して使用する：
  - 評価の要約
  - 実用価値の整理
  - 結び・提案文
- 感情表現は控えめにし、完成度・信頼性・継承性を軸に語る

■ casual_friendly（カジュアル・親しみ型）
- 文体：です・ます調（やわらかく会話的）
- 一人称「私は」を積極的に使用してよい
- 接客中に説明しているような距離感を意識する
- 専門用語は噛み砕き、短い文を基本とする
- 「私が好きな理由」「私が安心できる点」など主観を歓迎する

■ magazine_story（ストーリー型）
- 文体：です・ます調（やや抑制しつつ情緒を含める）
- 一人称「私は」は使用してよいが、語りすぎない
- 歴史や背景を“物語の流れ”として配置する
- 比喩は控えめに許可するが、誇張は禁止

────────────────────
【スタッフ追加入力 の扱いルール（重要）】
────────────────────
スタッフ追加入力は「販売現場での実体験・所感・技術的ポイント」として扱う。
いかなる場合も、内容を削除・無視してはならない。

■ casual_friendly の場合
- スタッフ追加入力の一人称「私は」を保持してよい
- 会話的・率直な表現として自然に本文へ組み込む

■ luxury / magazine_story / practical の場合
- スタッフ追加入力の内容は必ず反映する
- 以下の変換を行うこと：
  - 過度に砕けた表現は抑制する
  - 感情的断定は避ける
  - 「実用面での評価」「装着感の印象」
    「長期使用における安心材料」として再構成する
- 趣旨（何を評価しているか・何を勧めているか）は必ず保持する

────────────────────
【事実の優先順位（厳守）】
────────────────────
1. canonical_specs（マスタ＋オーバーライド）
2. remarks（販売者が確認済みの事実）
3. reference_url の本文内容

- 矛盾がある場合は必ず上位を採用する
- 想像・補完・事実に見える推測は禁止

────────────────────
【reference_url の使い方】
────────────────────
- 背景説明・文脈補足の材料としてのみ使用する
- 数値・仕様は canonical_specs のみを使用する
- 本文が薄い場合は、実用性・装着感を中心に構成する
- reference_url本文の文章表現をコピーしない（同義の言い換えにする）

────────────────────
【specs_text のルール】
────────────────────
- canonical_specs に含まれる項目のみ
- 箇条書き
- ラベル＋値のみ
- 装飾・評価表現は禁止
"""


# ----------------------------
# Tone profiles
# ----------------------------
TONE_PROFILES = {
    "practical": {
        "label": "実用・標準",
        "chars_with_url": (1200, 1600),
        "chars_no_url": (700, 1100),
        "instructions": """【文体・狙い】
- 製品情報サイトの紹介文のような、事実ベースで読みやすい文体
- です・ます調で、簡潔・平易に
- 一人称「私は」の使用は装着感の評価など実体験に限定（1〜2回まで）
- 一文は短〜中程度。情報を整理して伝える

【このトーンで必ずやること】
- 実用面の情報を優先して構成する
  優先順: 装着感 → 視認性 → 防水性能 → 操作性 → メンテナンス性 → 耐久性
- スペック情報を本文中に自然に組み込む（ただし羅列はしない）
- 具体的な使用場面を挙げる（ビジネス、アウトドア、水辺など）
- 素材の実用的な特徴に触れる（SSの耐傷性、チタンの軽さ、金無垢の重さなど）
- 客観的なトーンを維持する

【このトーンで禁止すること】
- ブランドの歴史や逸話（1文の簡潔な背景説明は許可）
- 感嘆や情緒的な表現（「美しい」「感動」「うっとり」等）
- 「！」の使用
- 比喩表現
- 他モデルとのコレクター的な比較
- 投資価値・資産性への言及
- 来店誘導

【語彙の方向性】
- 使う語彙例：「装着感」「視認性」「操作性」「日常使い」「耐久性」「メンテナンス」「実用的」
- 避ける語彙例：「崇高」「官能的」「物語」「象徴」「キラキラ」「映える」
- 中立的で情報的な語彙を選ぶ
""",
    },
    "luxury": {
        "label": "フォーマル・権威型",
        "chars_with_url": (1500, 2000),
        "chars_no_url": (800, 1200),
        "instructions": """【文体・狙い】
- 高級時計専門店のベテランスタッフが、時計に詳しい顧客に向けて書く文体
- です・ます調だが、格調を保つ
- 主語は省略傾向。対象物（時計、ムーブメント、ケース）を主語にする
- 一人称「私は」は評価の結論・提案文でのみ使用する

【このトーンで必ずやること】
- 他モデル・他リファレンスとの比較を積極的に入れる
- 数値は具体的に記述する（ケース厚、振動数、パワーリザーブ、部品点数など）
- ムーブメントの技術的特徴に言及する
- ブランドの歴史的文脈の中に製品を位置づける
- 括弧書きでの補足・注釈を許可する

【このトーンで禁止すること】
- 「！」の使用（句点「。」で終える）
- 「おすすめです」「ぜひ」「いかがでしょうか」等の直接的な購買呼びかけ
- 「〜ですよね」「〜しませんか？」等の共感・問いかけ型語尾
- 専門用語の噛み砕き説明（読者は知っている前提で書く）
- 日常生活のエピソードや個人的な体験談
- 来店誘導の文言

【語彙の方向性】
- 使う語彙例：「搭載」「継承」「採用」「施される」「呈する」「備える」「与えられる」
- 避ける語彙例：「かわいい」「すごい」「ぴったり」「お手頃」「コスパ」「キラキラ」
""",
    },
    "casual_friendly": {
        "label": "カジュアル・親しみ型",
        "chars_with_url": (1200, 1600),
        "chars_no_url": (700, 1100),
        "instructions": """【文体・狙い】
- 正規時計店のスタッフが、時計に詳しくないお客様に店頭で説明しているような文体
- です・ます調で、やわらかく会話的に
- 一人称「私は」を積極的に使い、自分の体験や感想を交える
- 一文は短く、テンポよく

【このトーンで必ずやること】
- 「私が実際に手に取って感じたこと」「私が好きな理由」など主観を前面に出す
- 専門用語を使う場合は必ず噛み砕いた説明を添える
- 着用シーン（ビジネス、カジュアル、デートなど）を具体的に提案する
- 「〜ですよね」「〜なんです」等の共感を求める語尾を使う
- 来店誘導を自然に組み込む（「ぜひ店頭でご覧ください」等）

【このトーンで禁止すること】
- 他モデルとの詳細なスペック比較（触れても簡潔に）
- 長い括弧書きの注釈
- 部品点数、振動数、石数などの技術的数値の羅列
- ブランド歴史の深い文脈説明（触れても2〜3文以内）
- 「だ・である」調の混入

【語彙の方向性】
- 使う語彙例：「つけ心地」「馴染む」「映える」「使いやすい」「合わせやすい」「気に入っている」「おすすめ」
- 避ける語彙例：「搭載」→「載っている/入っている」、「呈する」「施される」等の硬い受身表現
- 「！」の使用を許可するが、1段落に1回まで
""",
    },
    "magazine_story": {
        "label": "ストーリー型",
        "chars_with_url": (1500, 2000),
        "chars_no_url": (900, 1300),
        "instructions": """【文体・狙い】
- 時計専門メディアのライターが、読み物として楽しめる記事を書く文体
- です・ます調をベースに、情緒的な表現をやや許容する
- 一人称「私は」は記事の導入や結びで使用可。ただし記事の主役にはならない
- 長文と短文の緩急をつけ、読者を引き込むリズムを作る

【このトーンで必ずやること】
- 時系列に沿った展開で構成する（誕生→発展→現在の意義）
- 製品を歴史的・文化的文脈の中に位置づける
- 人物のエピソードや逸話を織り込む（ブランド創設者、デザイナー、著名な愛用者など）
- 導入で読者の興味を引くフック（印象的な事実、意外性のある情報）を置く
- 結びで製品の意義や価値を俯瞰的に述べる
- 比喩は控えめに使用可（ただし1記事で2〜3回まで）

【このトーンで禁止すること】
- 「！」の使用（句点「。」で終える）
- 直接的な購買呼びかけや来店誘導
- スペックの羅列（技術情報は物語の流れの中に自然に組み込む）
- 「私が買った理由」のような個人的な購買体験（書き手は観察者・語り手であり購入者ではない）
- 「〜ですよね」「〜しませんか？」等の共感・問いかけ型語尾

【語彙の方向性】
- 使う語彙例：「物語」「背景」「転換点」「象徴」「継承」「回帰」「原点」
- 時代や文化を語る言葉：「当時」「この頃」「時を経て」「今日では」
- 避ける語彙例：「おすすめ」「ぜひ」「コスパ」「映える」
""",
    },
}


def build_system(tone: str, has_reference_text: bool) -> str:
    profile = TONE_PROFILES.get(tone) or TONE_PROFILES.get("practical") or TONE_PROFILES["practical"]
    if has_reference_text:
        lo, hi = profile["chars_with_url"]
        depth_note = "reference_url本文があるため、背景・文脈を厚めに扱ってよい。"
    else:
        lo, hi = profile["chars_no_url"]
        depth_note = "reference_url本文が薄い/ないため、深掘りを抑制し、安全な範囲でまとめる。"

    return (
        SYSTEM_BASE
        + "\n"
        + profile["instructions"]
        + f"\n【intro_text の文字数】\n- 目安：{lo}〜{hi}文字\n- {depth_note}\n"
        + "\n【intro_text の構成】\n"
          "- 段落ごとに1テーマ（読み物として自然に）\n"
          "- 事実は canonical_specs / remarks / reference_url本文の範囲でのみ断定\n"
    )


# ----------------------------
# Trust source registry
# ----------------------------
TRUST_SOURCES: Dict[str, Dict[str, Any]] = {
    # A: ブランド公式
    "arminstrom.com": {"category": "A", "allowed_use": ["facts", "context"], "lang": "en"},
    "arnoldandson.com": {"category": "A", "allowed_use": ["facts", "context"], "lang": "en"},
    "audemarspiguet.com": {"category": "A", "allowed_use": ["facts", "context"], "lang": "en"},
    "backesandstrauss.com": {"category": "A", "allowed_use": ["facts", "context"], "lang": "en"},
    "ballwatch.com": {"category": "A", "allowed_use": ["facts", "context"], "lang": "en"},
    "baume-et-mercier.com": {"category": "A", "allowed_use": ["facts", "context"], "lang": "en"},
    "bellross.com": {"category": "A", "allowed_use": ["facts", "context"], "lang": "en"},
    "blancpain.com": {"category": "A", "allowed_use": ["facts", "context"], "lang": "en"},
    "breguet.com": {"category": "A", "allowed_use": ["facts", "context"], "lang": "en"},
    "breitling.com": {"category": "A", "allowed_use": ["facts", "context"], "lang": "en"},
    "bulgari.com": {"category": "A", "allowed_use": ["facts", "context"], "lang": "en"},
    "cartier.com": {"category": "A", "allowed_use": ["facts", "context"], "lang": "en"},
    "cartier.jp": {"category": "A", "allowed_use": ["facts", "context"], "lang": "ja"},
    "centurytime.com": {"category": "A", "allowed_use": ["facts", "context"], "lang": "en"},
    "chanel.com": {"category": "A", "allowed_use": ["facts", "context"], "lang": "both"},
    "chopard.com": {"category": "A", "allowed_use": ["facts", "context"], "lang": "en"},
    "chopard.jp": {"category": "A", "allowed_use": ["facts", "context"], "lang": "ja"},
    "chronoswiss.com": {"category": "A", "allowed_use": ["facts", "context"], "lang": "en"},
    "corum.ch": {"category": "A", "allowed_use": ["facts", "context"], "lang": "en"},
    "cvstos.com": {"category": "A", "allowed_use": ["facts", "context"], "lang": "en"},
    "delma.ch": {"category": "A", "allowed_use": ["facts", "context"], "lang": "en"},
    "eberhard-co-watches.ch": {"category": "A", "allowed_use": ["facts", "context"], "lang": "en"},
    "edox.com": {"category": "A", "allowed_use": ["facts", "context"], "lang": "en"},
    "franckmuller.com": {"category": "A", "allowed_use": ["facts", "context"], "lang": "en"},
    "franckmuller-japan.com": {"category": "A", "allowed_use": ["facts", "context"], "lang": "ja"},
    "frederiqueconstant.com": {"category": "A", "allowed_use": ["facts", "context"], "lang": "en"},
    "furlanmarri.com": {"category": "A", "allowed_use": ["facts", "context"], "lang": "en"},
    "geraldcharles.com": {"category": "A", "allowed_use": ["facts", "context"], "lang": "en"},
    "girard-perregaux.com": {"category": "A", "allowed_use": ["facts", "context"], "lang": "en"},
    "glashuette-original.com": {"category": "A", "allowed_use": ["facts", "context"], "lang": "en"},
    "gorillawatches.com": {"category": "A", "allowed_use": ["facts", "context"], "lang": "en"},
    "grand-seiko.com": {"category": "A", "allowed_use": ["facts", "context"], "lang": "both"},
    "h-moser.com": {"category": "A", "allowed_use": ["facts", "context"], "lang": "en"},
    "hamiltonwatch.com": {"category": "A", "allowed_use": ["facts", "context"], "lang": "en"},
    "harrywinston.com": {"category": "A", "allowed_use": ["facts", "context"], "lang": "en"},
    "hautlence.com": {"category": "A", "allowed_use": ["facts", "context"], "lang": "en"},
    "music-herbelin.com": {"category": "A", "allowed_use": ["facts", "context"], "lang": "en"},
    "herbelin.jp": {"category": "A", "allowed_use": ["facts", "context"], "lang": "ja"},
    "hublot.com": {"category": "A", "allowed_use": ["facts", "context"], "lang": "en"},
    "hysek.com": {"category": "A", "allowed_use": ["facts", "context"], "lang": "en"},
    "hytwatches.com": {"category": "A", "allowed_use": ["facts", "context"], "lang": "en"},
    "ikepod.com": {"category": "A", "allowed_use": ["facts", "context"], "lang": "en"},
    "iwc.com": {"category": "A", "allowed_use": ["facts", "context"], "lang": "en"},
    "jaeger-lecoultre.com": {"category": "A", "allowed_use": ["facts", "context"], "lang": "en"},
    "jaermann-stubi.com": {"category": "A", "allowed_use": ["facts", "context"], "lang": "en"},
    "junghans.de": {"category": "A", "allowed_use": ["facts", "context"], "lang": "en"},
    "lfreasonnance.com": {"category": "A", "allowed_use": ["facts", "context"], "lang": "en"},
    "longines.com": {"category": "A", "allowed_use": ["facts", "context"], "lang": "en"},
    "longines.jp": {"category": "A", "allowed_use": ["facts", "context"], "lang": "ja"},
    "louiserard.com": {"category": "A", "allowed_use": ["facts", "context"], "lang": "en"},
    "luminox.com": {"category": "A", "allowed_use": ["facts", "context"], "lang": "en"},
    "mauricelacroix.com": {"category": "A", "allowed_use": ["facts", "context"], "lang": "en"},
    "montblanc.com": {"category": "A", "allowed_use": ["facts", "context"], "lang": "en"},
    "moritz-grossmann.com": {"category": "A", "allowed_use": ["facts", "context"], "lang": "en"},
    "nomos-glashuette.com": {"category": "A", "allowed_use": ["facts", "context"], "lang": "en"},
    "norqain.com": {"category": "A", "allowed_use": ["facts", "context"], "lang": "en"},
    "omegawatches.com": {"category": "A", "allowed_use": ["facts", "context"], "lang": "en"},
    "omegawatches.jp": {"category": "A", "allowed_use": ["facts", "context"], "lang": "ja"},
    "oris.com": {"category": "A", "allowed_use": ["facts", "context"], "lang": "en"},
    "oris.ch": {"category": "A", "allowed_use": ["facts", "context"], "lang": "en"},
    "panerai.com": {"category": "A", "allowed_use": ["facts", "context"], "lang": "en"},
    "parmigiani.com": {"category": "A", "allowed_use": ["facts", "context"], "lang": "en"},
    "piaget.com": {"category": "A", "allowed_use": ["facts", "context"], "lang": "en"},
    "piaget.jp": {"category": "A", "allowed_use": ["facts", "context"], "lang": "ja"},
    "raymondweil.com": {"category": "A", "allowed_use": ["facts", "context"], "lang": "en"},
    "ressencewatches.com": {"category": "A", "allowed_use": ["facts", "context"], "lang": "en"},
    "rogerdubuis.com": {"category": "A", "allowed_use": ["facts", "context"], "lang": "en"},
    "rolex.com": {"category": "A", "allowed_use": ["facts", "context"], "lang": "en"},
    "rolex.org": {"category": "A", "allowed_use": ["facts", "context"], "lang": "en"},
    "tagheuer.com": {"category": "A", "allowed_use": ["facts", "context"], "lang": "en"},
    "tudorwatch.com": {"category": "A", "allowed_use": ["facts", "context"], "lang": "en"},
    "ulysse-nardin.com": {"category": "A", "allowed_use": ["facts", "context"], "lang": "en"},
    "zenith-watches.com": {"category": "A", "allowed_use": ["facts", "context"], "lang": "en"},
    "tissotshop.com": {"category": "A", "allowed_use": ["facts", "context"], "lang": "en"},
    "tissotwatches.com": {"category": "A", "allowed_use": ["facts", "context"], "lang": "en"},
    "renaudtixier.com": {"category": "A", "allowed_use": ["facts", "context"], "lang": "en"},
    "casio.com": {"category": "A", "allowed_use": ["facts", "context"], "lang": "both"},
    "casio.co.jp": {"category": "A", "allowed_use": ["facts", "context"], "lang": "ja"},
    "g-shock.jp": {"category": "A", "allowed_use": ["facts", "context"], "lang": "ja"},
    "gshock.com": {"category": "A", "allowed_use": ["facts", "context"], "lang": "en"},
    "baby-g.jp": {"category": "A", "allowed_use": ["facts", "context"], "lang": "ja"},
    "edifice-watches.com": {"category": "A", "allowed_use": ["facts", "context"], "lang": "en"},
    "protrek.jp": {"category": "A", "allowed_use": ["facts", "context"], "lang": "ja"},
    "oceanus.casio.jp": {"category": "A", "allowed_use": ["facts", "context"], "lang": "ja"},
    "citizen.jp": {"category": "A", "allowed_use": ["facts", "context"], "lang": "ja"},
    "citizen.co.jp": {"category": "A", "allowed_use": ["facts", "context"], "lang": "ja"},
    "campanola.jp": {"category": "A", "allowed_use": ["facts", "context"], "lang": "ja"},
    "the-citizen.jp": {"category": "A", "allowed_use": ["facts", "context"], "lang": "ja"},
    "seikowatches.com": {"category": "A", "allowed_use": ["facts", "context"], "lang": "both"},
    "seikowatcheshop.com": {"category": "A", "allowed_use": ["facts", "context"], "lang": "ja"},
    "garmin.com": {"category": "A", "allowed_use": ["facts", "context"], "lang": "en"},
    "garmin.co.jp": {"category": "A", "allowed_use": ["facts", "context"], "lang": "ja"},
    "lainewatches.com": {"category": "A", "allowed_use": ["facts", "context"], "lang": "en"},
    "ossoitaly.com": {"category": "A", "allowed_use": ["facts", "context"], "lang": "en"},
    "shellman.co.jp": {"category": "A", "allowed_use": ["facts", "context"], "lang": "ja"},
    "klasse14.com": {"category": "A", "allowed_use": ["facts", "context"], "lang": "en"},
    "mauronmusy.com": {"category": "A", "allowed_use": ["facts", "context"], "lang": "en"},
    "zerootime.com": {"category": "A", "allowed_use": ["facts", "context"], "lang": "ja"},
    "ztage.jp": {"category": "A", "allowed_use": ["facts", "context"], "lang": "ja"},

    # B: 正規店/販売店
    "eye-eye-isuzu.co.jp": {"category": "B", "allowed_use": ["context"], "lang": "ja"},
    "rasin.co.jp": {"category": "B", "allowed_use": ["context"], "lang": "ja"},
    "evance.co.jp": {"category": "B", "allowed_use": ["context"], "lang": "ja"},
    "tgsakai.blogo.jp": {"category": "B", "allowed_use": ["context"], "lang": "ja"},
    "shopblog.tomiya.co.jp": {"category": "B", "allowed_use": ["context"], "lang": "ja"},
    "e-ami.co.jp": {"category": "B", "allowed_use": ["context"], "lang": "ja"},
    "nsdo.co.jp": {"category": "B", "allowed_use": ["context"], "lang": "ja"},
    "basisspecies.jp": {"category": "B", "allowed_use": ["context"], "lang": "ja"},
    "l-sakae.co.jp": {"category": "B", "allowed_use": ["context"], "lang": "ja"},
    "isana-w.jp": {"category": "B", "allowed_use": ["context"], "lang": "ja"},
    "hidakahonten.jp": {"category": "B", "allowed_use": ["context"], "lang": "ja"},
    "hrd-web.com": {"category": "B", "allowed_use": ["context"], "lang": "ja"},
    "kamine.co.jp": {"category": "B", "allowed_use": ["context"], "lang": "ja"},
    "kobayashi-tokeiten.com": {"category": "B", "allowed_use": ["context"], "lang": "ja"},
    "tompkins.jp": {"category": "B", "allowed_use": ["context"], "lang": "ja"},
    "anshindo-grp.co.jp": {"category": "B", "allowed_use": ["context"], "lang": "ja"},
    "isseidostaff.blogspot.com": {"category": "B", "allowed_use": ["context"], "lang": "ja"},
    "lian-sakai-onlineshop.jp": {"category": "B", "allowed_use": ["context"], "lang": "ja"},
    "prive.co.jp": {"category": "B", "allowed_use": ["context"], "lang": "ja"},
    "koyanagi-tokei.com": {"category": "B", "allowed_use": ["context"], "lang": "ja"},
    "hassin.co.jp": {"category": "B", "allowed_use": ["context"], "lang": "ja"},
    "wing-rev.co.jp": {"category": "B", "allowed_use": ["context"], "lang": "ja"},
    "hf-age.com": {"category": "B", "allowed_use": ["context"], "lang": "ja"},
    "threec.jp": {"category": "B", "allowed_use": ["context"], "lang": "ja"},
    "j-paris.co.jp": {"category": "B", "allowed_use": ["context"], "lang": "ja"},
    "koharu1977.com": {"category": "B", "allowed_use": ["context"], "lang": "ja"},
    "jw-oomiya.co.jp": {"category": "B", "allowed_use": ["context"], "lang": "ja"},
    "ishida-watch.com": {"category": "B", "allowed_use": ["context"], "lang": "ja"},
    "tokia.co.jp": {"category": "B", "allowed_use": ["context"], "lang": "ja"},
    "hh-new.co.jp": {"category": "B", "allowed_use": ["context"], "lang": "ja"},
    "yoshidaweb.com": {"category": "B", "allowed_use": ["context"], "lang": "ja"},
    "couronne.info": {"category": "B", "allowed_use": ["context"], "lang": "ja"},
    "jackroad.co.jp": {"category": "B", "allowed_use": ["context"], "lang": "ja"},
    "bettyroad.co.jp": {"category": "B", "allowed_use": ["context"], "lang": "ja"},
    "housekihiroba.jp": {"category": "B", "allowed_use": ["context"], "lang": "ja"},
    "komehyo.co.jp": {"category": "B", "allowed_use": ["context"], "lang": "ja"},
    "ginza-rasin.com": {"category": "B", "allowed_use": ["context"], "lang": "ja"},
    "gmt-j.com": {"category": "B", "allowed_use": ["context"], "lang": "ja"},
    "moonphase.jp": {"category": "B", "allowed_use": ["context"], "lang": "ja"},
    "kawano-watch.com": {"category": "B", "allowed_use": ["context"], "lang": "ja"},
    "galleryrare.jp": {"category": "B", "allowed_use": ["context"], "lang": "ja"},
    "watchnian.com": {"category": "B", "allowed_use": ["context"], "lang": "ja"},

    # C: 時計専門メディア
    "webchronos.net": {"category": "C", "allowed_use": ["context", "opinion"], "lang": "ja"},
    "hodinkee.com": {"category": "C", "allowed_use": ["context", "opinion"], "lang": "en"},
    "hodinkee.jp": {"category": "C", "allowed_use": ["context", "opinion"], "lang": "ja"},
    "monochrome-watches.com": {"category": "C", "allowed_use": ["context", "opinion"], "lang": "en"},
    "timeandtidewatches.com": {"category": "C", "allowed_use": ["context", "opinion"], "lang": "en"},
    "fratellowatches.com": {"category": "C", "allowed_use": ["context", "opinion"], "lang": "en"},
    "watchesbysjx.com": {"category": "C", "allowed_use": ["context", "opinion"], "lang": "en"},
    "revolutionwatch.com": {"category": "C", "allowed_use": ["context", "opinion"], "lang": "en"},
    "swisswatches-magazine.com": {"category": "C", "allowed_use": ["context", "opinion"], "lang": "en"},
    "wornandwound.com": {"category": "C", "allowed_use": ["context", "opinion"], "lang": "en"},
    "ablogtowatch.com": {"category": "C", "allowed_use": ["context", "opinion"], "lang": "en"},
    "watchtime.com": {"category": "C", "allowed_use": ["context", "opinion"], "lang": "en"},
    "waqt.com": {"category": "C", "allowed_use": ["context", "opinion"], "lang": "en"},
    "watchmedia.co.jp": {"category": "C", "allowed_use": ["context", "opinion"], "lang": "ja"},
    "watch-media-online.com": {"category": "C", "allowed_use": ["context", "opinion"], "lang": "ja"},
    "pen-online.jp": {"category": "C", "allowed_use": ["context", "opinion"], "lang": "ja"},
    "tokeibegin.jp": {"category": "C", "allowed_use": ["context", "opinion"], "lang": "ja"},
    "watchfan.com": {"category": "C", "allowed_use": ["context", "opinion"], "lang": "ja"},
    "precious.jp": {"category": "C", "allowed_use": ["context", "opinion"], "lang": "ja"},
    "watch-tanaka.com": {"category": "C", "allowed_use": ["context", "opinion"], "lang": "ja"},
    "gressive.jp": {"category": "C", "allowed_use": ["context", "opinion"], "lang": "ja"},
    "watchlife.jp": {"category": "C", "allowed_use": ["context", "opinion"], "lang": "ja"},
    "tokeizanmai.com": {"category": "C", "allowed_use": ["context", "opinion"], "lang": "ja"},
    "esq-mag.jp": {"category": "C", "allowed_use": ["context", "opinion"], "lang": "ja"},
    "thewatchbox.com": {"category": "C", "allowed_use": ["context", "opinion"], "lang": "en"},
    "deployant.com": {"category": "C", "allowed_use": ["context", "opinion"], "lang": "en"},
    "quillandpad.com": {"category": "C", "allowed_use": ["context", "opinion"], "lang": "en"},
    "sjx.com": {"category": "C", "allowed_use": ["context", "opinion"], "lang": "en"},
    "thewatchpages.com": {"category": "C", "allowed_use": ["context", "opinion"], "lang": "en"},
    "timezone.com": {"category": "C", "allowed_use": ["context", "opinion"], "lang": "en"},
    "twobrokewatchsnobs.com": {"category": "C", "allowed_use": ["context", "opinion"], "lang": "en"},
    "watchlounge.com": {"category": "C", "allowed_use": ["context", "opinion"], "lang": "en"},
    "chrono24.jp": {"category": "C", "allowed_use": ["context", "opinion"], "lang": "ja"},
    "chrono24.com": {"category": "C", "allowed_use": ["context", "opinion"], "lang": "en"},
    "watchanalytics.io": {"category": "C", "allowed_use": ["context", "opinion"], "lang": "en"},

    # D: マーケット系（現在は空）
    # (empty)

    # E: UGC（補助）
    "wikipedia.org": {"category": "E", "allowed_use": ["context"], "lang": "both"},
    "note.com": {"category": "E", "allowed_use": ["context"], "lang": "ja"},

}


def get_source_policy(url: str) -> Tuple[bool, str, Optional[Dict[str, Any]]]:
    if not url:
        return False, "", None
    try:
        parsed = urlparse(url.strip())
        if parsed.scheme not in ("http", "https"):
            return False, "", None
        host = (parsed.hostname or "").lower()
        if not host:
            return False, "", None
    except Exception:
        return False, "", None

    for domain, policy in TRUST_SOURCES.items():
        if host == domain or host.endswith("." + domain):
            normalized_policy = dict(policy)
            normalized_policy.setdefault("lang", "both")
            return True, host, normalized_policy

    return False, host, None


# ----------------------------
# small helpers
# ----------------------------
def _safe_preview(text: str, n: int = 260) -> str:
    t = (text or "").strip().replace("\n", " ")
    return (t[:n] + "…") if len(t) > n else t


def _normalize_ref_variants(reference: str) -> List[str]:
    r = (reference or "").strip()
    if not r:
        return []
    r_up = r.upper()
    r_nosep = re.sub(r"[\s\.\-_/]", "", r_up)
    return list({r_up, r_nosep})


def _ref_hit(url: str, text: str, reference: str) -> bool:
    variants = _normalize_ref_variants(reference)
    if not variants:
        return False
    hay = (url or "") + "\n" + (text or "")
    hay_up = hay.upper()
    hay_nosep = re.sub(r"[\s\.\-_/]", "", hay_up)
    for v in variants:
        if v and (v in hay_up or v in hay_nosep):
            return True
    return False


# ----------------------------
# URL本文取得（安全版 / debug付き）
# ----------------------------
def fetch_page_text(url: str, max_chars: int = 8000, min_chars: int = 600) -> Tuple[str, bool, Dict[str, Any]]:
    meta: Dict[str, Any] = {
        "url": url,
        "allowed": False,
        "host": "",
        "parsed_host": "",
        "fetch_ok": False,
        "status": None,
        "method": "",
        "extracted_chars": 0,
        "extracted_preview": "",
        "filtered_reason": "",
        "cleaned": False,
        "cut_trigger": "",
    }

    url = (url or "").strip()
    if not url:
        meta["filtered_reason"] = "empty_url"
        return "", False, meta

    try:
        parsed_url = urlparse(url)
        netloc = (parsed_url.netloc or "").split("@")[-1].split(":")[0].strip().lower()
        parsed_host = netloc[4:] if netloc.startswith("www.") else netloc
        meta["parsed_host"] = parsed_host
    except Exception:
        meta["parsed_host"] = ""

    allowed, host, _policy = get_source_policy(url)
    meta["allowed"] = bool(allowed)
    meta["host"] = host
    if not allowed:
        meta["filtered_reason"] = "untrusted_domain"
        return "", False, meta

    try:
        resp = requests.get(url, timeout=15, headers={"User-Agent": "HoroloGen/1.0"})
        meta["status"] = getattr(resp, "status_code", None)
        resp.raise_for_status()
        meta["fetch_ok"] = True
        if not resp.encoding or resp.encoding.lower() == "iso-8859-1":
            resp.encoding = resp.apparent_encoding
    except Exception as e:
        meta["filtered_reason"] = f"request_failed:{type(e).__name__}"
        return "", False, meta

    soup = BeautifulSoup(resp.text, "html.parser")
    for tag in soup(["script", "style", "noscript", "header", "footer", "nav", "aside"]):
        tag.decompose()

    def _extract_text_from_root(root) -> str:
        parts: List[str] = []
        for el in root.find_all(["h1", "h2", "h3", "p", "li"]):
            t = el.get_text(" ", strip=True)
            if not t or len(t) < 15:
                continue
            parts.append(t)
        if not parts:
            text_all = root.get_text("\n", strip=True)
            lines = [l.strip() for l in text_all.splitlines() if len(l.strip()) >= 15]
            parts = lines
        return "\n".join(parts).strip()

    def _readability_like_fallback(doc_soup) -> str:
        # 1回だけの軽量フォールバック: 長文pを多く含む要素を優先
        best_text = ""
        best_len = 0
        for sel in ["main", "article", '[role="main"]', "body"]:
            node = doc_soup.select_one(sel)
            if not node:
                continue
            txt = _extract_text_from_root(node)
            if len(txt) > best_len:
                best_text = txt
                best_len = len(txt)
        return best_text

    def _clean_reference_text(raw_text: str) -> Tuple[str, bool, str]:
        if not raw_text:
            return "", False, ""

        jp_triggers = [
            "関連記事", "関連", "おすすめ", "人気記事", "話題の記事", "最新記事", "次の記事",
            "プライバシーポリシー", "利用規約",
        ]
        en_triggers = [
            "editors'", "recommended", "more from", "business news",
            "introducing", "talking watches", "cookie", "©",
        ]

        cleaned = False
        cut_trigger = ""
        lines = [ln.strip() for ln in (raw_text or "").splitlines() if ln.strip()]
        kept: List[str] = []
        for ln in lines:
            low = ln.lower()
            is_noise = False
            if len(ln) <= 80:
                if any(k in ln for k in jp_triggers):
                    is_noise = True
                if any(k in low for k in en_triggers):
                    is_noise = True
                if ("http://" in low or "https://" in low) and len(ln) <= 140:
                    is_noise = True
                if (ln.count("|") + ln.count("｜") + ln.count("/") + ln.count("・")) >= 4:
                    is_noise = True
            if is_noise:
                cleaned = True
                continue
            kept.append(ln)

        text2 = "\n".join(kept).strip()
        if not text2:
            text2 = (raw_text or "").strip()

        # セクション見出しが出たらそこで打ち切り
        lower = text2.lower()
        min_pos = None
        for trig in jp_triggers:
            pos = text2.find(trig)
            if pos >= 0 and (min_pos is None or pos < min_pos):
                min_pos = pos
                cut_trigger = trig
        for trig in en_triggers:
            pos = lower.find(trig)
            if pos >= 0 and (min_pos is None or pos < min_pos):
                min_pos = pos
                cut_trigger = trig

        if min_pos is not None and min_pos > 0:
            cut = text2[:min_pos].strip()
            if cut and cut != text2:
                text2 = cut
                cleaned = True

        return text2, cleaned, cut_trigger

    normalized_host = (meta.get("parsed_host") or "").lower()
    is_hodinkee_jp = normalized_host == "hodinkee.jp"

    text = ""
    selected_method = "fallback:document"

    if is_hodinkee_jp:
        selected_method = "hodinkee:enter"
        # hodinkee.jp は selector固定より、本文量が最大のブロックを採用する方が安定する
        roots = soup.find_all("article")
        if not roots:
            main_node = soup.select_one("main")
            if main_node:
                roots = [main_node]
        if not roots:
            role_main = soup.select_one('[role="main"]')
            if role_main:
                roots = [role_main]
        if not roots:
            body = soup.body
            if body:
                roots = body.find_all("div", recursive=False) or [body]

        best_text = ""
        best_score = -1
        best_total = -1
        for root in roots:
            # 候補ごとに独立して不要要素を除去する
            root_soup = BeautifulSoup(str(root), "html.parser")
            for tag in root_soup(["script", "style", "noscript", "header", "footer", "nav", "aside"]):
                tag.decompose()
            p_score = 0
            for p in root_soup.find_all("p"):
                p_text = p.get_text(" ", strip=True)
                if len(p_text) >= 15:
                    p_score += len(p_text)
            candidate_text = _extract_text_from_root(root_soup)
            total_score = len(candidate_text)
            if p_score > best_score or (p_score == best_score and total_score > best_total):
                best_score = p_score
                best_total = total_score
                best_text = candidate_text

        text = best_text.strip()
        if text:
            selected_method = "hodinkee:largest_block"

        if text and len(text) < min_chars:
            fb_text = _readability_like_fallback(soup)
            if len(fb_text) > len(text):
                text = fb_text
                selected_method = "hodinkee:fallback:readability_like"
    else:
        selectors = ["main", "article", '[role="main"]', ".article", ".post", ".content", ".entry-content", ".post-content"]
        for selector in selectors:
            root = soup.select_one(selector)
            if not root:
                continue
            candidate_text = _extract_text_from_root(root)
            if not candidate_text:
                continue
            if len(candidate_text) >= min_chars:
                text = candidate_text
                selected_method = f"selector:{selector}"
                break
            if len(candidate_text) > len(text):
                text = candidate_text
                selected_method = f"selector:{selector}(short)"

        if not text:
            text = _extract_text_from_root(soup)
            selected_method = "fallback:document"

        if text and len(text) < min_chars:
            fb_text = _readability_like_fallback(soup)
            if len(fb_text) > len(text):
                text = fb_text
                selected_method = f"{selected_method}->fallback:readability_like"

    meta["method"] = selected_method

    if not text:
        meta["filtered_reason"] = "no_text_extracted"
        return "", False, meta

    if bool(meta.get("allowed")):
        cleaned_text, cleaned_flag, cut_trigger = _clean_reference_text(text)
        if cleaned_text:
            text = cleaned_text
        meta["cleaned"] = bool(cleaned_flag)
        meta["cut_trigger"] = cut_trigger

    if len(text) > max_chars:
        text = text[:max_chars]

    meta["extracted_chars"] = len(text)
    meta["extracted_preview"] = _safe_preview(text, 220)

    ok = len(text) >= min_chars
    if not ok and not meta["filtered_reason"]:
        meta["filtered_reason"] = "too_short"
    return text, ok, meta


# ----------------------------
# facts 正規化（読みやすさのため）
# ----------------------------
FIELD_LABELS_ORDER = [
    ("price_jpy", "定価"),
    ("collection", "コレクション"),
    ("movement", "ムーブメント"),
    ("movement_caliber", "キャリバー"),
    ("case_material", "ケース素材"),
    ("case_size_mm", "ケース径"),
    ("case_thickness_mm", "ケース厚"),
    ("lug_width_mm", "ラグ幅"),
    ("dial_color", "文字盤カラー"),
    ("bracelet_strap", "ベルト"),
    ("buckle", "バックル"),
    ("water_resistance_m", "防水"),
    ("warranty_years", "保証"),
    ("remarks", "備考"),
]

BRACELET_MAP = {"bracelet": "ブレスレット", "strap": "ストラップ"}
MOVEMENT_MAP = {
    "manual winding": "手巻き",
    "manual": "手巻き",
    "hand-wound": "手巻き",
    "hand wound": "手巻き",
    "automatic": "自動巻き",
    "self-winding": "自動巻き",
    "self winding": "自動巻き",
    "quartz": "クォーツ",
}
CASE_MATERIAL_MAP = {
    "stainless_steel": "ステンレススチール",
    "stainless steel": "ステンレススチール",
    "steel": "ステンレススチール",
    "titanium": "チタン",
    "ceramic": "セラミック",
}
DIAL_COLOR_MAP = {
    "black": "ブラック",
    "white": "ホワイト",
    "blue": "ブルー",
    "silver": "シルバー",
    "gray": "グレー",
    "green": "グリーン",
}

def _clean_str(v: str) -> str:
    return (v or "").strip()

def _normalize_facts(facts: dict) -> dict:
    nf = {k: _clean_str(v) for k, v in (facts or {}).items()}

    bs = nf.get("bracelet_strap", "")
    if bs:
        nf["bracelet_strap"] = BRACELET_MAP.get(bs.lower(), bs)

    mv = nf.get("movement", "")
    if mv:
        nf["movement"] = MOVEMENT_MAP.get(mv.lower(), mv)

    cm = nf.get("case_material", "")
    if cm:
        nf["case_material"] = CASE_MATERIAL_MAP.get(cm.lower(), cm)

    dc = nf.get("dial_color", "")
    if dc:
        nf["dial_color"] = DIAL_COLOR_MAP.get(dc.lower(), dc)

    wr = nf.get("water_resistance_m", "")
    if wr:
        wr_clean = wr.replace("m", "").replace("M", "").strip()
        if wr_clean.isdigit():
            nf["water_resistance_m"] = f"{wr_clean}m防水"

    for key in ["case_size_mm", "case_thickness_mm", "lug_width_mm"]:
        val = nf.get(key, "")
        if val:
            val2 = val.replace("mm", "").replace("MM", "").strip()
            try:
                float(val2)
                nf[key] = f"{val2}mm"
            except Exception:
                pass

    wy = nf.get("warranty_years", "")
    if wy:
        wy2 = wy.replace("年", "").strip()
        if wy2.isdigit():
            nf["warranty_years"] = f"{wy2}年"

    return nf

def _specs_text_from_canonical(nf: dict) -> str:
    lines = []
    for key, label in FIELD_LABELS_ORDER:
        if key not in nf:
            continue
        v = _clean_str(nf.get(key, ""))
        if not v:
            continue
        lines.append(f"・{label}：{v}")
    return "\n".join(lines)


# ----------------------------
# User prompt builder
# ----------------------------
def build_user_prompt(payload: dict, reference_text: str) -> str:
    product = payload.get("product", {}) or {}
    facts = payload.get("facts", {}) or {}
    style = payload.get("style", {}) or {}
    options = payload.get("options", {}) or {}
    constraints = payload.get("constraints", {}) or {}
    ref_hit_false_urls = payload.get("_ref_hit_false_urls") or []
    if not isinstance(ref_hit_false_urls, list):
        ref_hit_false_urls = []
    ref_hit_false_urls = [u.strip() for u in ref_hit_false_urls if isinstance(u, str) and u.strip()]

    reference_url = (payload.get("reference_url") or payload.get("research", {}).get("reference_url") or "").strip()
    staff_additional_input = (payload.get("staff_additional_input") or payload.get("editor_note") or "").strip()

    brand = product.get("brand", "")
    ref = product.get("reference", "")
    tone = style.get("tone", "practical")

    facts_norm = _normalize_facts(facts)
    specs_template = _specs_text_from_canonical(facts_norm)

    include_brand_profile = bool(options.get("include_brand_profile", False))
    include_wearing_scenes = bool(options.get("include_wearing_scenes", False))

    target_intro = constraints.get("target_intro_chars", "") or constraints.get("max_intro_chars", "")
    target_note = f"- 目標文字数（参考）：{target_intro}文字\n" if target_intro else ""

    allowed, host, policy = get_source_policy(reference_url) if reference_url else (False, "", None)
    policy_line = ""
    if reference_url:
        if allowed and policy:
            policy_line = (
                f"- source_domain: {host}\n"
                f"- source_category: {policy.get('category')}\n"
                f"- allowed_use: {', '.join(policy.get('allowed_use', []))}\n"
            )
        else:
            policy_line = (
                f"- source_domain: {host or '(invalid)'}\n"
                f"- source_category: (untrusted)\n"
                f"- allowed_use: none\n"
            )

    if reference_text.strip():
        ref_block = f"""
[参考資料（スタッフが指定したURL群の本文抜粋）]
採用表示用URL（代表）: {reference_url if reference_url else "(未指定)"}
{policy_line}
本文抜粋（複数URLの結合）:
{reference_text}
"""
    else:
        ref_block = f"""
[参考資料]
採用表示用URL（代表）: {reference_url if reference_url else "(未指定)"}
{policy_line}
        本文: (なし)
"""

    ref_hit_false_block = ""
    if ref_hit_false_urls:
        joined = "\n".join([f"- {u}" for u in ref_hit_false_urls])
        ref_hit_false_block = f"""
[ref_hit=false 参考記事に関する制約]
以下の参考記事には対象商品の型番が含まれていません。
{joined}
この参考記事には対象商品の型番が含まれていません。デザインの印象、着用感、素材の質感、使い勝手などの定性的な情報のみを参考にしてください。サイズ、ムーブメント、価格などのスペック情報は一切参考にせず、確定スペックのみを使用してください。
"""

    return f"""以下の商品について、intro_text と specs_text を作成してください。

[商品]
- brand: {brand}
- reference: {ref}

[トーン]
{tone}

[オプション]
- include_brand_profile: {include_brand_profile}
- include_wearing_scenes: {include_wearing_scenes}

[スタッフ追加入力（スタッフの主観・経験・逸話。intro_textに必ず反映）]
{staff_additional_input if staff_additional_input else "(未入力)"}

[canonical_specs（確定事実）]
{json.dumps(facts_norm, ensure_ascii=False, indent=2)}

[specs_text の出力テンプレ（この形式で必ず出力）]
{specs_template}

{ref_block}
{ref_hit_false_block}

[重要ルール]
- intro_text にはスタッフ追加入力の内容を自然に統合する（未入力の場合は触れない）
- スタッフ追加入力を末尾にラベル付きで機械的に追記しない
- スタッフ追加入力は必要に応じて言い換えてよいが、意味は保持する
- 事実の捏造はしない
- 語り手は「正規時計店スタッフ」。一人称の使い方はトーン規定に従う
- 事実の優先順位：canonical_specs > remarks > reference_url本文
- 矛盾がある場合は必ず上位を採用する
- reference_url本文の文章表現をコピーしない（同義の言い換えにする）
- specs_text は必ず出力する（空にしない）
- specs_text は上のテンプレをそのまま使う（順序・形式を変えない）
{target_note}
"""


# ----------------------------
# Hype ban
# ----------------------------
BANNED_PHRASES = [
    "買うのは今です", "買うのは今", "今買わないと損", "絶対買い", "買わない理由がない", "マストバイ",
    "値上げ前に急げ", "入手困難で後悔", "このチャンスを逃すな",
    "必ず値上がり", "資産になる",
]

def validate_no_hype(text: str) -> list:
    t = text or ""
    return [p for p in BANNED_PHRASES if p in t]


# ----------------------------
# Tool extract helpers
# ----------------------------
def _message_text(message) -> str:
    blocks = getattr(message, "content", None) or []
    parts = []

    for b in blocks:
        # dict形式
        if isinstance(b, dict):
            if b.get("type") == "text":
                t = (b.get("text") or "").strip()
                if t:
                    parts.append(t)
            continue

        # オブジェクト形式
        if getattr(b, "type", None) == "text":
            t = (getattr(b, "text", "") or "").strip()
            if t:
                parts.append(t)

    return "\n".join(parts).strip()

def _extract_json_object_from_text(txt: str) -> Dict[str, Any]:
    """
    tool_use が返らない場合の保険：
    返答本文にJSONが含まれていたら拾う。
    """
    if not txt:
        return {}
    # ```json ... ``` を優先して拾う
    m = re.search(r"```(?:json)?\s*({.*?})\s*```", txt, flags=re.DOTALL)
    if m:
        s = m.group(1).strip()
        try:
            d = json.loads(s)
            return d if isinstance(d, dict) else {}
        except Exception:
            pass

    # 最初の { ... } を拾う（雑だが保険として）
    m2 = re.search(r"({.*})", txt, flags=re.DOTALL)
    if m2:
        s2 = m2.group(1).strip()
        try:
            d = json.loads(s2)
            return d if isinstance(d, dict) else {}
        except Exception:
            return {}
    return {}

def _pick_tool_input(message) -> Dict[str, Any]:
    """
    Anthropic SDKの返却が
    - オブジェクト形式 (b.type, b.input, b.name)
    - dict形式 (b["type"], b["input"], b["name"])
    のどちらでも拾えるようにする

    さらに tool名が "return_article" のものを優先して拾う。
    """
    blocks = getattr(message, "content", None) or []

    # 1) まず "return_article" を優先して探す
    for b in blocks:
        # dict形式
        if isinstance(b, dict):
            if b.get("type") == "tool_use" and b.get("name") == "return_article":
                data = b.get("input") or {}
                return data if isinstance(data, dict) else {}
            continue

        # オブジェクト形式
        if getattr(b, "type", None) == "tool_use" and getattr(b, "name", None) == "return_article":
            data = getattr(b, "input", None) or {}
            return data if isinstance(data, dict) else {}

    # 2) fallback: どれでもいいので最初の tool_use を拾う
    for b in blocks:
        if isinstance(b, dict):
            if b.get("type") == "tool_use":
                data = b.get("input") or {}
                return data if isinstance(data, dict) else {}
            continue

        if getattr(b, "type", None) == "tool_use":
            data = getattr(b, "input", None) or {}
            return data if isinstance(data, dict) else {}

    return {}

def _is_valid_article_dict(d: Dict[str, Any]) -> bool:
    if not isinstance(d, dict):
        return False
    it = (d.get("intro_text") or "").strip()
    st = (d.get("specs_text") or "").strip()
    return bool(it) and bool(st)


# ----------------------------
# Similarity (language-agnostic char n-gram Jaccard)
# ----------------------------
def _ngram_set(text: str, n: int = 3, max_len: int = 9000) -> set:
    t = (text or "").strip()
    if not t:
        return set()
    # remove urls and excessive whitespace
    t = re.sub(r"https?://\S+", " ", t)
    t = re.sub(r"\s+", "", t)
    t = t[:max_len]
    if len(t) < n:
        return {t}
    return {t[i:i+n] for i in range(0, len(t) - n + 1)}

def similarity_percent(a: str, b: str) -> int:
    A = _ngram_set(a, 3)
    B = _ngram_set(b, 3)
    if not A or not B:
        return 0
    inter = len(A & B)
    union = len(A | B)
    if union == 0:
        return 0
    return int(round((inter / union) * 100))

def similarity_level(pct: int) -> str:
    # 運用で調整前提（まずは安全寄り）
    if pct >= 35:
        return "red"
    if pct >= 20:
        return "yellow"
    return "blue"


# ----------------------------
# Main entry: generate_article
# rewrite_mode:
#   "none"  : 通常生成
#   "force" : 必ず1回だけ「言い換え再生成」
#   "auto"  : 類似が高いときだけ1回だけ言い換え
# ----------------------------
def generate_article(payload: dict, rewrite_mode: str = "none") -> tuple[str, str, Dict[str, Any]]:
    client = _get_client()

    product = payload.get("product", {}) or {}
    ref_code = (product.get("reference") or "").strip()

    # 参考URL（最大4本: ja最大3 + en最大1 を想定）
    raw_reference_urls = payload.get("reference_urls") or []
    if not isinstance(raw_reference_urls, list):
        raw_reference_urls = []

    reference_url_entries: List[Dict[str, str]] = []
    for item in raw_reference_urls:
        if isinstance(item, dict):
            u = (item.get("url") or "").strip()
            if not u:
                continue
            lang = (item.get("lang") or "ja").strip().lower()
            if lang not in {"ja", "en"}:
                lang = "ja"
            source = (item.get("source") or "manual").strip() or "manual"
            reference_url_entries.append({"url": u, "lang": lang, "source": source})
        elif isinstance(item, str):
            u = item.strip()
            if u:
                reference_url_entries.append({"url": u, "lang": "ja", "source": "manual"})

    legacy = (payload.get("reference_url") or payload.get("research", {}).get("reference_url") or "").strip()
    if legacy:
        reference_url_entries = [{"url": legacy, "lang": "ja", "source": "manual"}] + [
            x for x in reference_url_entries if x.get("url") != legacy
        ]

    deduped_entries: List[Dict[str, str]] = []
    seen_urls = set()
    for entry in reference_url_entries:
        u = (entry.get("url") or "").strip()
        if not u or u in seen_urls:
            continue
        seen_urls.add(u)
        deduped_entries.append(entry)
    reference_url_entries = deduped_entries[:4]

    raw_reference_prefetch = payload.get("reference_prefetch") or []
    prefetch_by_url: Dict[str, Dict[str, Any]] = {}
    if isinstance(raw_reference_prefetch, list):
        for item in raw_reference_prefetch:
            if not isinstance(item, dict):
                continue
            u = (item.get("url") or "").strip()
            if not u or u in prefetch_by_url:
                continue
            meta = item.get("meta") if isinstance(item.get("meta"), dict) else {}
            prefetch_by_url[u] = {
                "text": (item.get("text") or ""),
                "ok": bool(item.get("ok", False)),
                "meta": meta,
            }

    per_url_debug: List[Dict[str, Any]] = []
    per_url_texts: List[Dict[str, Any]] = []

    best_url = ""
    best_text = ""
    chosen_url = ""
    chosen_text = ""
    chosen_reason = ""

    # URL0件でも debug を残す
    if not reference_url_entries:
        per_url_debug.append({
            "url": "(no urls)",
            "allowed": False,
            "host": "",
            "parsed_host": "",
            "fetch_ok": False,
            "fetch_status": "fail",
            "status": None,
            "method": "",
            "chars": 0,
            "char_count": 0,
            "lang": "ja",
            "source": "manual",
            "ok": False,
            "prefetch_used": False,
            "cleaned": False,
            "cut_trigger": "",
            "preview": "",
            "filtered_reason": "no_reference_urls_in_payload",
            "ref_hit": False,
        })

    # 1) 取得
    for entry in reference_url_entries:
        u = (entry.get("url") or "").strip()
        lang = (entry.get("lang") or "ja").strip().lower()
        if lang not in {"ja", "en"}:
            lang = "ja"
        source = (entry.get("source") or "manual").strip() or "manual"
        prefetch_used = False
        if u in prefetch_by_url:
            prefetch_item = prefetch_by_url.get(u) or {}
            text = (prefetch_item.get("text") or "")
            ok = bool(prefetch_item.get("ok", False))
            raw_meta = prefetch_item.get("meta") if isinstance(prefetch_item.get("meta"), dict) else {}
            meta = {
                "allowed": raw_meta.get("allowed"),
                "host": raw_meta.get("host"),
                "parsed_host": raw_meta.get("parsed_host"),
                "fetch_ok": raw_meta.get("fetch_ok"),
                "status": raw_meta.get("status"),
                "method": raw_meta.get("method"),
                "extracted_chars": raw_meta.get("extracted_chars", 0),
                "extracted_preview": raw_meta.get("extracted_preview", ""),
                "filtered_reason": raw_meta.get("filtered_reason", ""),
                "cleaned": bool(raw_meta.get("cleaned", False)),
                "cut_trigger": raw_meta.get("cut_trigger", ""),
            }
            prefetch_used = True
        else:
            text, ok, meta = fetch_page_text(u)
        hit = _ref_hit(u, text, ref_code)
        meta["ref_hit"] = bool(hit)

        per_url_texts.append({
            "url": u,
            "text": text or "",
            "lang": lang,
            "source": source,
            "ref_hit": bool(hit),
        })

        per_url_debug.append({
            "url": u,
            "lang": lang,
            "source": source,
            "allowed": meta.get("allowed"),
            "host": meta.get("host"),
            "parsed_host": meta.get("parsed_host", ""),
            "fetch_ok": meta.get("fetch_ok"),
            "fetch_status": "ok" if meta.get("fetch_ok") else "fail",
            "status": meta.get("status"),
            "method": meta.get("method"),
            "chars": meta.get("extracted_chars", 0),
            "char_count": int(len(text or "")),
            "ok": bool(ok),
            "prefetch_used": bool(prefetch_used),
            "cleaned": bool(meta.get("cleaned", False)),
            "cut_trigger": meta.get("cut_trigger", ""),
            "preview": meta.get("extracted_preview", ""),
            "filtered_reason": meta.get("filtered_reason", ""),
            "ref_hit": bool(hit),
        })

        if len(text) > len(best_text):
            best_text = text
            best_url = u

    # 2) 採用URL選定（ref_hit優先 → ok優先 → 最長）
    for item in per_url_debug:
        if item.get("ok") and item.get("ref_hit"):
            chosen_url = item.get("url", "")
            chosen_text = next((x["text"] for x in per_url_texts if x["url"] == chosen_url), "")
            chosen_reason = "リファレンス一致のため採用"
            break

    if not chosen_url:
        for item in per_url_debug:
            if item.get("ok"):
                chosen_url = item.get("url", "")
                chosen_text = next((x["text"] for x in per_url_texts if x["url"] == chosen_url), "")
                chosen_reason = "本文が十分だったので採用"
                break

    if not chosen_url:
        chosen_url = best_url
        chosen_text = best_text
        if chosen_url:
            chosen_reason = "一番長い本文だったので採用"
        else:
            chosen_reason = "参考URLなし（本文なし）"

    # 3) 本文結合（各URL最大2500 / 合計最大10000）
    combined_blocks = []
    total = 0
    for item in per_url_texts:
        t = (item.get("text") or "").strip()
        if not t:
            continue
        url = item.get("url") or ""
        lang = item.get("lang") or "ja"
        source = item.get("source") or "manual"
        hit = bool(item.get("ref_hit"))
        t = t[:2500]
        lang_note = ""
        if lang == "en":
            lang_note = "この記事は英語です。定性情報のみを参考にし、翻訳調にせず自然な日本語で書いてください。\n"
        block = (
            f"URL: {url}\n"
            f"lang: {lang}\n"
            f"source: {source}\n"
            f"ref_hit: {hit}\n"
            f"{lang_note}"
            f"本文抜粋:\n{t}"
        )
        if total + len(block) > 10000:
            break
        combined_blocks.append(block)
        total += len(block)

    combined_reference_text = "\n\n---\n\n".join(combined_blocks).strip()

    ref_hit_false_urls = [
        item.get("url", "")
        for item in per_url_debug
        if bool(item.get("ok")) and (not bool(item.get("ref_hit"))) and bool(item.get("url"))
    ]
    payload["_ref_hit_false_urls"] = [u for u in ref_hit_false_urls if isinstance(u, str) and u.strip()]

    # build_user_prompt が表示に使う代表URL
    payload["reference_url"] = chosen_url

    has_ref = bool(len(combined_reference_text) >= 400)
    tone = (payload.get("style", {}) or {}).get("tone", "practical")
    system = build_system(tone, has_reference_text=has_ref)
    user_prompt = build_user_prompt(payload, combined_reference_text)

    def _call_claude(sys_text: str, u_prompt: str, temperature: float = 0.3):
        return client.messages.create(
            model=MODEL,
            max_tokens=2300,
            temperature=temperature,
            system=sys_text,
            messages=[{"role": "user", "content": u_prompt}],
            tools=[ARTICLE_TOOL],
            tool_choice={"type": "tool", "name": "return_article"},
        )

    def _extract_once(sys_text: str, u_prompt: str, temperature: float = 0.3) -> Dict[str, Any]:
        # 1) tools を使って通常実行
        msg = _call_claude(sys_text, u_prompt, temperature=temperature)
        print(f"[HoroloGen] MODEL={MODEL}")
        data = _pick_tool_input(msg)
        if isinstance(data, dict) and data:
            return data

        # LOG: tool_use が無い/空の場合の診断ログ（原因追跡用）
        if not data:
            try:
                blocks = getattr(msg, "content", None) or []
                types = []
                tool_names = []
                for b in blocks:
                    if isinstance(b, dict):
                        types.append(b.get("type"))
                        if b.get("type") == "tool_use":
                            tool_names.append(b.get("name"))
                    else:
                        types.append(getattr(b, "type", None))
                        if getattr(b, "type", None) == "tool_use":
                            tool_names.append(getattr(b, "name", None))
                preview = (_message_text(msg) or "")[:500]
                print(f"[HoroloGen] WARN: tool_use missing/empty. stop_reason={getattr(msg,'stop_reason',None)} content_types={types} tool_names={tool_names} text_preview={preview}")
            except Exception:
                pass

        # 2) tool_use が無い場合：textからJSONを拾う保険
        txt = _message_text(msg)
        data2 = _extract_json_object_from_text(txt)
        if _is_valid_article_dict(data2):
            return data2

        # 3) 最終保険：tools無しで「JSONだけ出せ」で再試行して拾う
        sys2 = sys_text + "\n\n【重要】ツール出力が失敗した場合は、本文にJSONのみで返してください。"
        u2 = u_prompt + "\n\n【出力形式】必ずJSONのみ。キーは intro_text と specs_text の2つ。余計な文章は禁止。"
        try:
            msg2 = client.messages.create(
                model=MODEL,
                max_tokens=2300,
                temperature=temperature,
                system=sys2,
                messages=[{"role": "user", "content": u2}],
            )
            txt2 = _message_text(msg2)
            data3 = _extract_json_object_from_text(txt2)
            if _is_valid_article_dict(data3):
                return data3
        except Exception:
            pass

        # ダメなら空を返す（呼び元で例外）
        return {}

    # 4) 通常生成（tool不正に備えて最大2回）
    data = _extract_once(system, user_prompt, temperature=0.3)
    if not _is_valid_article_dict(data):
        data2 = _extract_once(system, user_prompt, temperature=0.3)
        if _is_valid_article_dict(data2):
            data = data2

    intro = (data.get("intro_text") or "").strip()
    specs = (data.get("specs_text") or "").strip()

    # specs_text 欠損時の保険：canonical から生成
    if intro and not specs:
        facts = payload.get("facts", {}) or {}
        facts_norm = _normalize_facts(facts)
        specs = _specs_text_from_canonical(facts_norm).strip()

    if not intro or not specs:
        raise ValueError(f"Claudeのtool出力が不正です。keys={list(data.keys())} input={data}")

    hits = validate_no_hype(intro)
    if hits:
        raise ValueError(f"煽り表現が検出されました: {hits}")

    # 5) 類似度
    sim_before = similarity_percent(intro, combined_reference_text)
    lvl_before = similarity_level(sim_before)

    # 6) 言い換え再生成（任意/自動/強制）
    do_rewrite = False
    if rewrite_mode == "force":
        do_rewrite = True
    elif rewrite_mode == "auto" and sim_before >= 35:
        do_rewrite = True

    sim_after = sim_before
    lvl_after = lvl_before

    if do_rewrite:
        rewrite_system = system + "\n\n【言い換え再生成（重要）】\n- reference_url本文の表現の“言い回し”は流用しない\n- 構成と文のつながりを組み替え、同義の言い換えを徹底する\n- 固有名詞・型番・数値は保持する\n"

        rewrite_user = user_prompt + f"""

[追加指示：言い換え再生成]
- 直前に作った intro_text のドラフトを渡すので、意味を保持しつつ大きく言い換えてください。
- reference_url本文との表現重複を避けるため、言い回し・語順・段落構成を組み替えてください。
- specs_text はテンプレの形式を維持してください（内容はcanonical_specs準拠）。

[直前のintro_textドラフト]
{intro}
"""
        data_r = _extract_once(rewrite_system, rewrite_user, temperature=0.4)
        if not _is_valid_article_dict(data_r):
            data_r2 = _extract_once(rewrite_system, rewrite_user, temperature=0.4)
            if _is_valid_article_dict(data_r2):
                data_r = data_r2

        intro_r = (data_r.get("intro_text") or "").strip()
        specs_r = (data_r.get("specs_text") or "").strip()

        if intro_r:
            intro = intro_r
        if specs_r:
            specs = specs_r

        hits2 = validate_no_hype(intro)
        if hits2:
            raise ValueError(f"煽り表現が検出されました: {hits2}")

        sim_after = similarity_percent(intro, combined_reference_text)
        lvl_after = similarity_level(sim_after)

    ref_meta = {
        "selected_reference_url": chosen_url,
        "selected_reference_reason": chosen_reason,
        "selected_reference_chars": len(chosen_text or ""),
        "combined_reference_chars": len(combined_reference_text or ""),
        "combined_reference_preview": _safe_preview(combined_reference_text, 360),
        "reference_urls_debug": per_url_debug,

        # similarity (final)
        "similarity_percent": int(sim_after),
        "similarity_level": str(lvl_after),

        # debug
        "similarity_before_percent": int(sim_before),
        "similarity_before_level": str(lvl_before),
        "rewrite_applied": bool(do_rewrite),
    }

    return intro, specs, ref_meta
