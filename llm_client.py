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
_api_key = os.getenv("ANTHROPIC_API_KEY")
if not _api_key:
    raise RuntimeError("ANTHROPIC_API_KEY が未設定です（export してから起動してください）")
client = Anthropic(api_key=_api_key)


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
【editor_note の扱いルール（重要）】
────────────────────
editor_note は「販売現場での実体験・所感・技術的ポイント」として扱う。
いかなる場合も、内容を削除・無視してはならない。

■ casual_friendly の場合
- editor_note の一人称「私は」を保持してよい
- 会話的・率直な表現として自然に本文へ組み込む

■ luxury / magazine_story / practical の場合
- editor_note の内容は必ず反映する
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
- 実用性重視、読みやすい（です・ます調）
- 使い勝手（装着感、視認性、耐久性、メンテ性）を中心に
- 煽り・断定的な購買誘導は禁止
""",
    },
    "luxury": {
        "label": "フォーマル・権威型",
        "chars_with_url": (1500, 2000),
        "chars_no_url": (800, 1200),
        "instructions": """【文体・狙い】
- 高級時計専門店らしい格調高い文体（です・ます調）
- ブランドの歴史や技術的価値、信頼性、長期使用価値を重視
- 誇張・煽りは禁止（資産性に触れる場合も断定しない）
- 主観は「私は〜と考えます」の形で控えめに
""",
    },
    "casual_friendly": {
        "label": "カジュアル・親しみ型",
        "chars_with_url": (1200, 1600),
        "chars_no_url": (700, 1100),
        "instructions": """【文体・狙い】
- 読みやすく親しみやすい（です・ます調）
- 日常での使いやすさ（着用シーン、装着感、防水、扱いやすさ）を重視
- 専門用語は噛み砕いて説明
- 店頭でお客様に話しかけるような自然な口調
- 一人称「私は」を積極的に使用してよい
""",
    },
    "magazine_story": {
        "label": "ストーリー型",
        "chars_with_url": (1500, 2000),
        "chars_no_url": (900, 1300),
        "instructions": """【文体・狙い】
- 背景や文脈を物語的に構成（です・ます調）
- 感情に訴えるが誇張はしない
- 比喩は控えめに許可
- 事実の断定は canonical_specs / remarks / reference_url本文の範囲のみ
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
    "omegawatches.com": {"category": "A", "allowed_use": ["facts", "context"]},
    "omegawatches.jp": {"category": "A", "allowed_use": ["facts", "context"]},
    "cartier.com": {"category": "A", "allowed_use": ["facts", "context"]},
    "grand-seiko.com": {"category": "A", "allowed_use": ["facts", "context"]},
    "iwc.com": {"category": "A", "allowed_use": ["facts", "context"]},
    "panerai.com": {"category": "A", "allowed_use": ["facts", "context"]},

    # B: 正規店/販売店
    "eye-eye-isuzu.co.jp": {"category": "B", "allowed_use": ["context"]},
    "rasin.co.jp": {"category": "B", "allowed_use": ["context"]},
    "evance.co.jp": {"category": "B", "allowed_use": ["context"]},

    # C: 時計専門メディア
    "webchronos.net": {"category": "C", "allowed_use": ["context", "opinion"]},
    "hodinkee.com": {"category": "C", "allowed_use": ["context", "opinion"]},
    "monochrome-watches.com": {"category": "C", "allowed_use": ["context", "opinion"]},
    "timeandtidewatches.com": {"category": "C", "allowed_use": ["context", "opinion"]},
    "fratellowatches.com": {"category": "C", "allowed_use": ["context", "opinion"]},
    "watchesbysjx.com": {"category": "C", "allowed_use": ["context", "opinion"]},
    "revolutionwatch.com": {"category": "C", "allowed_use": ["context", "opinion"]},
    "swisswatches-magazine.com": {"category": "C", "allowed_use": ["context", "opinion"]},
    "wornandwound.com": {"category": "C", "allowed_use": ["context", "opinion"]},

    # D: マーケット系（用途限定）
    "chrono24.com": {"category": "D", "allowed_use": ["market", "context"]},

    # E: UGC（補助）
    "wikipedia.org": {"category": "E", "allowed_use": ["context"]},
    "note.com": {"category": "E", "allowed_use": ["context"]},
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
            return True, host, policy

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
        "fetch_ok": False,
        "status": None,
        "method": "",
        "extracted_chars": 0,
        "extracted_preview": "",
        "filtered_reason": "",
    }

    url = (url or "").strip()
    if not url:
        meta["filtered_reason"] = "empty_url"
        return "", False, meta

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

    # できるだけ本文っぽいところを拾う
    candidates = []
    for selector in ["main", "article", '[role="main"]', ".article", ".post", ".content", ".entry-content", ".post-content"]:
        el = soup.select_one(selector)
        if el:
            candidates.append((selector, el))

    if candidates:
        sel, root = candidates[0]
        meta["method"] = f"selector:{sel}"
    else:
        root = soup
        meta["method"] = "fallback:document"

    parts = []
    for el in root.find_all(["h1", "h2", "h3", "p", "li"]):
        text = el.get_text(" ", strip=True)
        if not text:
            continue
        if len(text) < 15:
            continue
        parts.append(text)

    if not parts:
        text_all = root.get_text("\n", strip=True)
        lines = [l.strip() for l in text_all.splitlines() if len(l.strip()) >= 15]
        parts = lines

    text = "\n".join(parts).strip()

    if not text:
        meta["filtered_reason"] = "no_text_extracted"
        return "", False, meta

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

    reference_url = (payload.get("reference_url") or payload.get("research", {}).get("reference_url") or "").strip()
    editor_note = (payload.get("editor_note") or "").strip()

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

    return f"""以下の商品について、intro_text と specs_text を作成してください。

[商品]
- brand: {brand}
- reference: {ref}

[トーン]
{tone}

[オプション]
- include_brand_profile: {include_brand_profile}
- include_wearing_scenes: {include_wearing_scenes}

[editor_note（スタッフの主観・経験・逸話。intro_textに必ず反映）]
{editor_note if editor_note else "(未入力)"}

[canonical_specs（確定事実）]
{json.dumps(facts_norm, ensure_ascii=False, indent=2)}

[specs_text の出力テンプレ（この形式で必ず出力）]
{specs_template}

{ref_block}

[重要ルール]
- intro_text には editor_note の内容を必ず含める（未入力の場合は触れない）
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
    product = payload.get("product", {}) or {}
    ref_code = (product.get("reference") or "").strip()

    # 参考URL（最大3本）
    reference_urls = payload.get("reference_urls") or []
    if not isinstance(reference_urls, list):
        reference_urls = []

    legacy = (payload.get("reference_url") or payload.get("research", {}).get("reference_url") or "").strip()
    if legacy:
        reference_urls = [legacy] + [u for u in reference_urls if u != legacy]

    reference_urls = [u.strip() for u in reference_urls if isinstance(u, str) and u.strip()][:3]

    per_url_debug: List[Dict[str, Any]] = []
    per_url_texts: List[Dict[str, str]] = []

    best_url = ""
    best_text = ""
    chosen_url = ""
    chosen_text = ""
    chosen_reason = ""

    # URL0件でも debug を残す
    if not reference_urls:
        per_url_debug.append({
            "url": "(no urls)",
            "allowed": False,
            "host": "",
            "fetch_ok": False,
            "status": None,
            "method": "",
            "chars": 0,
            "ok": False,
            "preview": "",
            "filtered_reason": "no_reference_urls_in_payload",
            "ref_hit": False,
        })

    # 1) 取得
    for u in reference_urls:
        text, ok, meta = fetch_page_text(u)
        hit = _ref_hit(u, text, ref_code)
        meta["ref_hit"] = bool(hit)

        per_url_texts.append({"url": u, "text": text or ""})

        per_url_debug.append({
            "url": u,
            "allowed": meta.get("allowed"),
            "host": meta.get("host"),
            "fetch_ok": meta.get("fetch_ok"),
            "status": meta.get("status"),
            "method": meta.get("method"),
            "chars": meta.get("extracted_chars", 0),
            "ok": bool(ok),
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

    # 3) 本文結合（各URL最大2500 / 合計最大8000）
    combined_blocks = []
    total = 0
    for item in per_url_texts:
        t = (item.get("text") or "").strip()
        if not t:
            continue
        t = t[:2500]
        block = f"URL: {item['url']}\n本文抜粋:\n{t}"
        if total + len(block) > 8000:
            break
        combined_blocks.append(block)
        total += len(block)

    combined_reference_text = "\n\n---\n\n".join(combined_blocks).strip()

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
                print(f"[HoroloGen] WARN: tool_use missing/empty. stop_reason={getattr(msg,'stop_r