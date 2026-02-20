import os
import re
import logging
import requests
from urllib.parse import unquote, urlparse
from typing import List, Dict, Any, Tuple, Optional
from anthropic import Anthropic

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

# Anthropic web_search の allowed_domains に渡すと 400 になる既知ドメイン
CRAWL_BLOCKED_DOMAINS = {
    "hodinkee.com",
    "hodinkee.jp",
}

# 自動探索で除外するドメイン（TRUST_SOURCESは維持。手動入力fetchには適用しない）
AUTO_DISCOVERY_EXCLUDE_DOMAINS = {
    "omegawatches.com",
}


def _normalize_domain(d: str) -> str:
    host = (d or "").strip().lower()
    if not host:
        return ""
    host = host.split("@")[-1]
    host = host.split(":")[0]
    if host.startswith("www."):
        host = host[4:]
    return host


def _exclude_crawl_blocked_domains(domains: List[str]) -> List[str]:
    out: List[str] = []
    seen = set()
    blocked = {_normalize_domain(x) for x in CRAWL_BLOCKED_DOMAINS}
    for d in domains or []:
        nd = _normalize_domain(d)
        if not nd or nd in blocked or nd in seen:
            continue
        seen.add(nd)
        out.append(nd)
    return out


def _extract_blocked_domains_from_error_message(msg: str) -> List[str]:
    s = (msg or "").strip()
    if not s:
        return []
    if "The following domains are not accessible" not in s:
        return []
    m = re.search(r"\[([^\]]+)\]", s)
    if not m:
        return []
    chunk = m.group(1)
    parts = [p.strip().strip("'\"") for p in chunk.split(",")]
    out: List[str] = []
    seen = set()
    for p in parts:
        nd = _normalize_domain(p)
        if not nd or nd in seen:
            continue
        seen.add(nd)
        out.append(nd)
    return out


def _passes_auto_discovery_filter(url: str) -> Tuple[bool, str]:
    """
    自動探索で採用するURLの共通フィルタ。
    - 除外ドメイン
    - chrono24 は /magazine/ 配下のみ許可
    """
    u = (url or "").strip()
    if not u:
        return False, "auto_invalid_url"
    try:
        p = urlparse(u)
        host = _normalize_domain(p.netloc or p.hostname or "")
        path = (p.path or "").strip().lower()
    except Exception:
        return False, "auto_invalid_url"

    for d in AUTO_DISCOVERY_EXCLUDE_DOMAINS:
        nd = _normalize_domain(d)
        if host == nd or host.endswith("." + nd):
            return False, "auto_excluded_domain"

    if host in {"chrono24.com", "chrono24.jp"}:
        if not (path == "/magazine" or path.startswith("/magazine/")):
            return False, "auto_disallowed_path"

    return True, ""


def _collect_allowed_domains_by_lang(source_map: Dict[str, Dict[str, Any]], allowed_langs: List[str]) -> List[str]:
    langs = {str(x).strip().lower() for x in (allowed_langs or []) if str(x).strip()}
    out: List[str] = []
    for d, p in (source_map or {}).items():
        if not isinstance(p, dict):
            continue
        lang = str(p.get("lang") or "").strip().lower()
        if lang in langs:
            out.append(d)
    return _exclude_crawl_blocked_domains(out)


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
    blocked_known = {_normalize_domain(x) for x in CRAWL_BLOCKED_DOMAINS}
    normalized_input = [_normalize_domain(x) for x in (allowed_domains or []) if _normalize_domain(x)]
    removed_blocked = sorted({d for d in normalized_input if d in blocked_known})
    filtered_allowed_domains = _exclude_crawl_blocked_domains(allowed_domains or [])
    logging.info(
        "[HoroloGen] web_search クエリ: %s (allowed_domains=%s, removed_blocked=%s, max_urls=%s)",
        q,
        len(filtered_allowed_domains),
        removed_blocked,
        max_urls,
    )
    def _call_web_search(domains: List[str]):
        return client.messages.create(
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
                "allowed_domains": domains[:200],
            }],
        )

    try:
        msg = _call_web_search(filtered_allowed_domains)
    except Exception as e:
        err_text = str(e)
        blocked_from_error = _extract_blocked_domains_from_error_message(err_text)
        if blocked_from_error:
            retry_domains = [
                d for d in filtered_allowed_domains
                if _normalize_domain(d) not in {_normalize_domain(x) for x in blocked_from_error}
            ]
            logging.error(
                "[HoroloGen] web_search エラー: %s (blocked=%s) -> 1回だけ再試行",
                e,
                blocked_from_error,
            )
            try:
                msg = _call_web_search(retry_domains)
            except Exception as e2:
                logging.error("[HoroloGen] web_search エラー(再試行): %s", e2)
                return []
        else:
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
    allowed_domains = _exclude_crawl_blocked_domains(list(llmc.TRUST_SOURCES.keys()))
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
        pass_auto, reason = _passes_auto_discovery_filter(cand)
        if not pass_auto:
            logging.info(
                "[HoroloGen] auto_discovery URL除外: url=%s filtered_reason=%s",
                cand,
                reason,
            )
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

    en_domains = _collect_allowed_domains_by_lang(llmc.TRUST_SOURCES or {}, ["en"])
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
            pass_auto, reason = _passes_auto_discovery_filter(cand)
            if not pass_auto:
                logging.info(
                    "[HoroloGen] auto_discovery URL除外: url=%s filtered_reason=%s",
                    cand,
                    reason,
                )
                continue
            if (policy or {}).get("lang") != "en":
                continue
            out.append(cand)
            if len(out) >= max(1, max_urls):
                return out
    return out


def discover_reference_urls(brand: str, reference: str, max_urls: int = 3) -> Tuple[List[str], Dict[str, Any]]:
    """
    brand + reference から URL候補を最大3本返す。
    - APIキーが無い場合は [] を返す（手入力運用にフォールバック）
    - 信頼ドメイン(ホワイトリスト)で最後にフィルタ
    """
    brand = (brand or "").strip()
    reference = (reference or "").strip()
    logging.info(
        "[HoroloGen] discover_reference_urls 呼出し開始 brand=%s reference=%s max_urls=%s",
        brand,
        reference,
        max_urls,
    )

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

    ja_domains = _collect_allowed_domains_by_lang(llmc.TRUST_SOURCES or {}, ["ja", "both"])
    if not ja_domains:
        debug["auto_url_reason"] = "no_ja_domains_after_filter"
        logging.info("[HoroloGen] discover_reference_urls 結果: 0件")
        return [], debug

    # クエリ設計（日本語）
    queries = [
        f"{brand} {reference} レビュー",
        f"{brand} {reference} 実機",
        f"{brand} {reference} 評判",
    ]

    seen = set()
    candidates: List[str] = []

    for q in queries:
        urls = _anthropic_web_search(q, allowed_domains=ja_domains, max_urls=8)
        debug["queries"].append({"q": q, "used": "anthropic_web_search", "results": len(urls)})
        debug["raw_results"].append({"q": q, "urls": urls})

        for u in urls:
            if u in seen:
                continue
            seen.add(u)

            allowed, _host, _policy = llmc.get_source_policy(u)
            if not allowed:
                continue
            pass_auto, reason = _passes_auto_discovery_filter(u)
            if not pass_auto:
                logging.info(
                    "[HoroloGen] auto_discovery URL除外: url=%s filtered_reason=%s",
                    u,
                    reason,
                )
                continue

            candidates.append(u)
            if len(candidates) >= max_urls:
                break
        if len(candidates) >= max_urls:
            break

    debug["filtered_results"] = candidates[:max_urls]
    debug["auto_url_used"] = True
    debug["auto_url_reason"] = "ok" if candidates else "no_results_after_whitelist"
    logging.info("[HoroloGen] discover_reference_urls 結果: %s件", len(candidates[:max_urls]))

    return candidates[:max_urls], debug
