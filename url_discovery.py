import os
import re
import logging
import requests
from urllib.parse import unquote, urlparse
from typing import List, Dict, Any, Tuple, Optional
from anthropic import Anthropic

# 公式ドメイン優先（必要に応じて増やせます）
OFFICIAL_DOMAINS = {
    "omega": ["omegawatches.jp", "omegawatches.com"],
    "cartier": ["cartier.com"],
    "grand_seiko": ["grand-seiko.com"],
    "iwc": ["iwc.com"],
    "panerai": ["panerai.com"],
}

GOOGLE_CSE_ENDPOINT = "https://www.googleapis.com/customsearch/v1"
ANTHROPIC_MODEL = os.getenv("HOROLOGEN_CLAUDE_MODEL", "claude-sonnet-4-5")

_client: Optional[Anthropic] = None

BRAND_JA_MAP = {
    "cartier": "カルティエ",
    "omega": "オメガ",
    "grand_seiko": "グランドセイコー",
    "grand-seiko": "グランドセイコー",
    "iwc": "IWC",
    "panerai": "パネライ",
}


def _get_client() -> Optional[Anthropic]:
    global _client
    if _client is not None:
        return _client
    api_key = (os.getenv("ANTHROPIC_API_KEY") or "").strip()
    if not api_key:
        return None
    try:
        _client = Anthropic(api_key=api_key)
        return _client
    except Exception:
        return None


def _extract_urls_from_text(text: str) -> List[str]:
    if not text:
        return []
    urls = re.findall(r"https?://[^\s\]\)\}\>\"']+", text)
    return [u.strip().rstrip(".,;:") for u in urls if u.strip()]


def _extract_urls_from_message(message) -> List[str]:
    urls: List[str] = []
    blocks = getattr(message, "content", None) or []
    for b in blocks:
        data = b if isinstance(b, dict) else getattr(b, "__dict__", None) or {}
        if not isinstance(data, dict):
            continue

        # text block fallback
        t = data.get("text")
        if isinstance(t, str):
            urls.extend(_extract_urls_from_text(t))

        # known URL-bearing keys
        for k in ("url", "source_url", "link"):
            v = data.get(k)
            if isinstance(v, str) and v.startswith(("http://", "https://")):
                urls.append(v.strip())

        # nested search results (tool payloads)
        nested = data.get("search_results") or data.get("results") or []
        if isinstance(nested, list):
            for item in nested:
                if not isinstance(item, dict):
                    continue
                for k in ("url", "source_url", "link"):
                    v = item.get(k)
                    if isinstance(v, str) and v.startswith(("http://", "https://")):
                        urls.append(v.strip())
                snippet = item.get("text") or item.get("snippet")
                if isinstance(snippet, str):
                    urls.extend(_extract_urls_from_text(snippet))
    # de-dup while preserving order
    out: List[str] = []
    seen = set()
    for u in urls:
        if u not in seen:
            seen.add(u)
            out.append(u)
    return out


def _anthropic_web_search(query: str, allowed_domains: List[str], max_urls: int = 5) -> List[str]:
    client = _get_client()
    if client is None:
        logging.info("[HoroloGen] web_search スキップ: ANTHROPIC_API_KEY未設定")
        return []
    q = (query or "").strip()
    if not q:
        logging.info("[HoroloGen] web_search スキップ: query empty")
        return []
    logging.info(
        "[HoroloGen] web_search クエリ: %s (allowed_domains=%s, max_urls=%s)",
        q,
        len(allowed_domains or []),
        max_urls,
    )
    try:
        msg = client.messages.create(
            model=ANTHROPIC_MODEL,
            max_tokens=800,
            temperature=0,
            messages=[{
                "role": "user",
                "content": (
                    "検索して、関連するURLだけを返してください。\n"
                    f"query: {q}\n"
                    "出力はURLのみ（複数行）にしてください。"
                ),
            }],
            tools=[{
                "type": "web_search_20250305",
                "name": "web_search",
                "max_uses": 1,
                "allowed_domains": allowed_domains[:200],
            }],
        )
    except Exception as e:
        logging.error("[HoroloGen] web_search エラー: %s", e)
        return []

    urls = _extract_urls_from_message(msg)
    logging.info("[HoroloGen] web_search 結果: %s件", len(urls))
    return urls[:max(1, max_urls)]


def _extract_title_or_keywords_from_failed_url(failed_url: str) -> str:
    u = (failed_url or "").strip()
    if not u:
        return ""
    # 1) HEADでタイトル相当ヘッダが取れれば使う
    try:
        h = requests.head(u, timeout=8, allow_redirects=True, headers={"User-Agent": "HoroloGen/1.0"})
        for key in ("x-title", "title"):
            v = (h.headers.get(key) or "").strip()
            if v:
                return v
    except Exception:
        pass

    # 2) GETで<title>抽出を試す
    try:
        g = requests.get(u, timeout=10, allow_redirects=True, headers={"User-Agent": "HoroloGen/1.0"})
        m = re.search(r"<title[^>]*>(.*?)</title>", g.text or "", flags=re.IGNORECASE | re.DOTALL)
        if m:
            title = re.sub(r"\s+", " ", m.group(1)).strip()
            if title:
                return title
    except Exception:
        pass

    # 3) URL path からキーワード抽出
    parsed = urlparse(u)
    path = unquote(parsed.path or "")
    tokens = [t for t in re.split(r"[\/_\-\.]+", path) if t]
    host_brand = (parsed.hostname or "").lower().split(".")[0]
    if host_brand:
        tokens.insert(0, BRAND_JA_MAP.get(host_brand, host_brand))
    normalized = []
    for t in tokens:
        t2 = t.strip()
        if not t2:
            continue
        normalized.append(BRAND_JA_MAP.get(t2.lower(), t2))
    return " ".join(normalized[:8]).strip()


def fallback_search_from_failed_url(failed_url: str, max_urls: int = 1) -> List[str]:
    """
    本文取得に失敗したURLから代替URLを探索する。
    - Anthropic web_search tool を使用
    - TRUST_SOURCES のホワイトリスト通過URLのみ採用
    - 失敗時は [] を返す
    """
    u = (failed_url or "").strip()
    if not u:
        return []
    if _get_client() is None:
        return []

    keyword = _extract_title_or_keywords_from_failed_url(u)
    if not keyword:
        return []

    # 循環import回避
    import llm_client as llmc
    allowed_domains = list(llmc.TRUST_SOURCES.keys())
    raw_urls = _anthropic_web_search(keyword, allowed_domains=allowed_domains, max_urls=8)

    out: List[str] = []
    seen = set()
    for cand in raw_urls:
        if cand in seen:
            continue
        seen.add(cand)
        allowed, _host, _policy = llmc.get_source_policy(cand)
        if not allowed:
            continue
        out.append(cand)
        if len(out) >= max(1, max_urls):
            break
    return out


def discover_english_urls(
    brand: str,
    reference: str,
    collection: Optional[str] = None,
    max_urls: int = 1,
) -> List[str]:
    """
    英語記事を自動補完する。
    - Anthropic web_search tool を使用
    - TRUST_SOURCES のうち lang='en' のドメインのみ採用
    - 失敗時は [] を返す
    """
    b = (brand or "").strip()
    r = (reference or "").strip()
    c = (collection or "").strip()
    if not b or not r:
        return []
    if _get_client() is None:
        return []

    # 循環import回避
    import llm_client as llmc

    en_domains: List[str] = []
    for d, p in (llmc.TRUST_SOURCES or {}).items():
        if not isinstance(p, dict):
            continue
        if (p.get("lang") or "").strip() == "en":
            en_domains.append(d)
    if not en_domains:
        return []

    queries = [
        f"{b} {r} review",
        f"{b} {r} hands-on",
    ]
    if c:
        queries.append(f"{b} {c} review")

    out: List[str] = []
    seen = set()
    for q in queries:
        raw_urls = _anthropic_web_search(q, allowed_domains=en_domains, max_urls=8)
        for cand in raw_urls:
            if cand in seen:
                continue
            seen.add(cand)
            allowed, _host, policy = llmc.get_source_policy(cand)
            if not allowed:
                continue
            if (policy or {}).get("lang") != "en":
                continue
            out.append(cand)
            if len(out) >= max(1, max_urls):
                return out
    return out


def _cse_search(q: str, top_k: int = 5) -> Tuple[List[str], Dict[str, Any]]:
    """
    Google Custom Search JSON API (通常版) を使って検索結果URLを返す。
    環境変数が無ければ空で返す（エラーにしない）。
    """
    api_key = os.getenv("GOOGLE_CSE_API_KEY", "").strip()
    cx = os.getenv("GOOGLE_CSE_CX", "").strip()

    meta = {"query": q, "used": False, "status": None, "error": ""}
    logging.info("[HoroloGen] CSE クエリ: %s (top_k=%s)", q, top_k)

    if not api_key or not cx:
        meta["error"] = "missing_env(GOOGLE_CSE_API_KEY/GOOGLE_CSE_CX)"
        logging.error("[HoroloGen] CSE エラー: %s", meta["error"])
        return [], meta

    params = {
        "key": api_key,
        "cx": cx,
        "q": q,
        "num": min(max(top_k, 1), 10),
    }

    try:
        r = requests.get(GOOGLE_CSE_ENDPOINT, params=params, timeout=15)
        meta["used"] = True
        meta["status"] = r.status_code
        r.raise_for_status()
        data = r.json() or {}
        items = data.get("items") or []
        urls = []
        for it in items:
            link = (it.get("link") or "").strip()
            if link:
                urls.append(link)
        logging.info("[HoroloGen] CSE 結果: %s件 status=%s", len(urls), meta.get("status"))
        return urls, meta
    except Exception as e:
        meta["error"] = str(e)
        logging.error("[HoroloGen] CSE エラー: %s", e)
        return [], meta


def discover_reference_urls(brand: str, reference: str, max_urls: int = 3) -> Tuple[List[str], Dict[str, Any]]:
    """
    brand + reference から URL候補を最大3本返す。
    - APIキーが無い場合は [] を返す（手入力運用にフォールバック）
    - 信頼ドメイン(ホワイトリスト)で最後にフィルタ
    """
    brand = (brand or "").strip()
    reference = (reference or "").strip()

    debug: Dict[str, Any] = {
        "auto_url_used": False,
        "auto_url_reason": "",
        "queries": [],
        "raw_results": [],
        "filtered_results": [],
    }

    if not brand or not reference:
        debug["auto_url_reason"] = "brand_or_reference_empty"
        return [], debug

    # llm_client のホワイトリスト判定を使う（循環import回避のため関数内import）
    import llm_client as llmc

    # クエリ設計（少数・堅め）
    queries = []
    # 1) 基本クエリ（広く）
    queries.append(f"{brand} {reference}")

    # 2) 公式ドメイン優先クエリ（ある場合のみ）
    for dom in OFFICIAL_DOMAINS.get(brand, [])[:2]:
        queries.append(f"site:{dom} {reference}")

    # 3) 型番だけ（短い型番で引っかける）
    queries.append(reference)

    seen = set()
    candidates: List[str] = []

    for q in queries:
        urls, meta = _cse_search(q, top_k=7)
        debug["queries"].append({"q": q, **meta})

        # APIキーが無い場合：最初のクエリ時点で missing_env が入るので即終了
        if meta.get("error", "").startswith("missing_env"):
            debug["auto_url_reason"] = "missing_api_key_or_cx"
            return [], debug

        debug["raw_results"].append({"q": q, "urls": urls})

        for u in urls:
            if u in seen:
                continue
            seen.add(u)

            allowed, host, _policy = llmc.get_source_policy(u)
            if not allowed:
                continue

            candidates.append(u)
            if len(candidates) >= max_urls:
                break
        if len(candidates) >= max_urls:
            break

    debug["filtered_results"] = candidates[:max_urls]
    debug["auto_url_used"] = True
    debug["auto_url_reason"] = "ok" if candidates else "no_results_after_whitelist"

    return candidates[:max_urls], debug
