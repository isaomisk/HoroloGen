import os
import requests
from typing import List, Dict, Any, Tuple

# 公式ドメイン優先（必要に応じて増やせます）
OFFICIAL_DOMAINS = {
    "omega": ["omegawatches.jp", "omegawatches.com"],
    "cartier": ["cartier.com"],
    "grand_seiko": ["grand-seiko.com"],
    "iwc": ["iwc.com"],
    "panerai": ["panerai.com"],
}

GOOGLE_CSE_ENDPOINT = "https://www.googleapis.com/customsearch/v1"


def _cse_search(q: str, top_k: int = 5) -> Tuple[List[str], Dict[str, Any]]:
    """
    Google Custom Search JSON API (通常版) を使って検索結果URLを返す。
    環境変数が無ければ空で返す（エラーにしない）。
    """
    api_key = os.getenv("GOOGLE_CSE_API_KEY", "").strip()
    cx = os.getenv("GOOGLE_CSE_CX", "").strip()

    meta = {"query": q, "used": False, "status": None, "error": ""}

    if not api_key or not cx:
        meta["error"] = "missing_env(GOOGLE_CSE_API_KEY/GOOGLE_CSE_CX)"
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
        return urls, meta
    except Exception as e:
        meta["error"] = str(e)
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
