"""Market data helpers used by the FastAPI bridge.

The hot-stock popularity endpoint from Eastmoney is unstable: in many
responses it only includes popularity rank + raw security code (sc/rk), while
stock name and latest percent change must be enriched from quote endpoints.
This module therefore uses a multi-source fallback chain and a short in-memory
cache so that the frontend can reliably display name + latest pct change.
"""

from __future__ import annotations

import json
import re
import time
from typing import Any, Iterable


_HOT_STOCKS_CACHE: dict[str, Any] = {"expires_at": 0.0, "data": []}
_QUOTE_CACHE: dict[str, Any] = {"expires_at": 0.0, "data": {}}
HOT_STOCKS_TTL_SECONDS = 180
QUOTE_TTL_SECONDS = 600


def _safe_float(value: Any) -> float | None:
    if value is None:
        return None
    if isinstance(value, (int, float)):
        try:
            return float(value)
        except Exception:
            return None
    text = str(value).strip().replace(",", "")
    if not text or text in {"-", "--", "N/A", "None", "none", "nan", "NaN", "null"}:
        return None
    if text.endswith("%"):
        text = text[:-1]
    try:
        return float(text)
    except Exception:
        return None


def _first_value(item: dict[str, Any], keys: Iterable[str]) -> Any:
    for key in keys:
        value = item.get(key)
        if value not in (None, "", "--", "-"):
            return value
    return None


def _chunked(values: list[str], size: int) -> Iterable[list[str]]:
    for i in range(0, len(values), size):
        yield values[i : i + size]


def _clean_code(value: Any) -> str:
    """Normalize SH600519 / 600519.SH / 1.600519 / 600519 to six digits."""
    text = str(value or "").strip().upper()
    if not text:
        return ""
    if text.startswith(("SH", "SZ", "BJ")) and len(text) >= 8:
        text = text[2:]
    if "." in text:
        parts = text.split(".")
        # Eastmoney secid can be 1.600519, exchange suffix can be 600519.SH.
        for part in reversed(parts):
            if part.isdigit() and len(part) == 6:
                return part
        for part in parts:
            if part.isdigit() and len(part) == 6:
                return part
    match = re.search(r"(\d{6})", text)
    return match.group(1) if match else ""


def _infer_market(code: str, raw_code: str = "", market: str = "") -> str:
    raw = str(raw_code or "").strip().upper()
    explicit = str(market or "").strip().upper()
    if explicit in {"SH", "SZ", "BJ"}:
        return explicit
    if raw.startswith(("SH", "SZ", "BJ")):
        return raw[:2]
    if raw.endswith(".SH"):
        return "SH"
    if raw.endswith(".SZ"):
        return "SZ"
    if raw.endswith(".BJ"):
        return "BJ"
    if code.startswith("6"):
        return "SH"
    if code.startswith(("8", "4", "9")):
        return "BJ"
    return "SZ"


def _market_symbol(code: str, market: str | None = None, style: str = "eastmoney") -> str | None:
    code = _clean_code(code)
    if not code:
        return None
    market = _infer_market(code, market=market or "")
    if style == "sina":
        prefix = {"SH": "sh", "SZ": "sz", "BJ": "bj"}.get(market, "sz")
        return f"{prefix}{code}"
    if style == "raw":
        return f"{market}{code}"
    # Eastmoney secid: Shanghai=1, Shenzhen/Beijing=0 in most quote APIs.
    prefix = "1" if market == "SH" else "0"
    return f"{prefix}.{code}"


def _normalize_hot_record(item: dict[str, Any], index: int) -> dict[str, Any] | None:
    raw_code = _first_value(
        item,
        (
            "sc",
            "SECURITY_CODE",
            "securityCode",
            "code",
            "stockCode",
            "f12",
            "股票代码",
        ),
    )
    code = _clean_code(raw_code)
    market = _infer_market(code, str(raw_code or ""), str(item.get("market") or item.get("mkt") or item.get("f13") or ""))
    raw_normalized = str(raw_code or "").strip().upper() or _market_symbol(code, market, "raw") or code

    name = _first_value(
        item,
        (
            "name",
            "stockName",
            "stock_name",
            "SECURITY_SHORT_NAME",
            "SECURITY_NAME_ABBR",
            "SECURITY_NAME",
            "securityName",
            "security_name",
            "sn",
            "sname",
            "f14",
            "股票名称",
            "股票简称",
            "名称",
        ),
    )
    rank = _first_value(item, ("rk", "rank", "RANK", "排名")) or index
    pct_change = _safe_float(
        _first_value(
            item,
            (
                "pct_change",
                "pctChange",
                "changePercent",
                "change_percent",
                "zdf",
                "ZDF",
                "涨跌幅",
                "f3",
            ),
        )
    )

    if not code and not name:
        return None

    return {
        "rank": int(_safe_float(rank) or index),
        "code": code,
        "name": str(name).strip() if name else code,
        "market": market,
        "raw_code": raw_normalized,
        "pct_change": pct_change,
        "enrich_source": "rank_payload" if name or pct_change is not None else "none",
    }


def _extract_record_list(payload: Any) -> list[dict[str, Any]]:
    """Find the first list of dicts in an unstable API payload."""
    if isinstance(payload, list):
        return [x for x in payload if isinstance(x, dict)]
    if not isinstance(payload, dict):
        return []

    candidates = [
        payload.get("data"),
        payload.get("rank"),
        payload.get("list"),
        payload.get("result"),
        payload.get("diff"),
    ]
    for candidate in candidates:
        if isinstance(candidate, list):
            return [x for x in candidate if isinstance(x, dict)]
        if isinstance(candidate, dict):
            nested = _extract_record_list(candidate)
            if nested:
                return nested
    for value in payload.values():
        nested = _extract_record_list(value)
        if nested:
            return nested
    return []


def _http_request(method: str, url: str, **kwargs: Any) -> Any:
    try:
        from curl_cffi import requests as cr

        return cr.request(method, url, impersonate="chrome120", **kwargs)
    except Exception:
        import requests

        return requests.request(method, url, **kwargs)


def _decode_json_response(response: Any) -> Any:
    text = (response.text or "").strip()
    if not text:
        return None
    # Eastmoney occasionally returns JSONP-like payloads.
    if not text.startswith(("{", "[")) and "(" in text and text.endswith(")"):
        text = text[text.find("(") + 1 : -1]
    try:
        return json.loads(text)
    except Exception:
        try:
            return response.json()
        except Exception:
            return None


def _http_get_json(url: str, params: dict[str, Any] | None = None, timeout: int = 8) -> Any:
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120 Safari/537.36",
        "Accept": "application/json,text/plain,*/*",
        "Referer": "https://quote.eastmoney.com/",
    }
    try:
        response = _http_request("GET", url, params=params, headers=headers, timeout=timeout)
        if response.status_code != 200:
            return None
        return _decode_json_response(response)
    except Exception:
        return None


def _http_post_json(url: str, body: dict[str, Any], timeout: int = 8) -> Any:
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120 Safari/537.36",
        "Accept": "application/json,text/plain,*/*",
        "Content-Type": "application/json",
        "Origin": "https://emapp.eastmoney.com",
        "Referer": "https://emapp.eastmoney.com/",
    }
    try:
        response = _http_request("POST", url, json=body, headers=headers, timeout=timeout)
        if response.status_code != 200:
            return None
        return _decode_json_response(response)
    except Exception:
        return None


def _extract_diff(payload: Any) -> list[dict[str, Any]]:
    data = (payload or {}).get("data") if isinstance(payload, dict) else None
    diff = (data or {}).get("diff") if isinstance(data, dict) else None
    if isinstance(diff, dict):
        diff = list(diff.values())
    return [x for x in diff or [] if isinstance(x, dict)]


def _fetch_eastmoney_ulist_map(records: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    """Fetch exact quote data for the hot stock codes through Eastmoney ulist."""
    secids: list[str] = []
    for record in records:
        secid = _market_symbol(str(record.get("code") or ""), str(record.get("market") or ""), "eastmoney")
        if secid and secid not in secids:
            secids.append(secid)
    if not secids:
        return {}

    url = "https://push2.eastmoney.com/api/qt/ulist.np/get"
    result: dict[str, dict[str, Any]] = {}
    for batch in _chunked(secids, 80):
        params = {
            "fltt": "2",
            "invt": "2",
            "fields": "f12,f13,f14,f2,f3,f4,f5,f6",
            "secids": ",".join(batch),
            "_": str(int(time.time() * 1000)),
        }
        payload = _http_get_json(url, params=params, timeout=8)
        for item in _extract_diff(payload):
            code = _clean_code(item.get("f12"))
            if not code:
                continue
            result[code] = {
                "name": str(item.get("f14") or "").strip(),
                "pct_change": _safe_float(item.get("f3")),
                "source": "eastmoney_ulist",
            }
    return result


def _fetch_eastmoney_clist_map_for_codes(target_codes: set[str]) -> dict[str, dict[str, Any]]:
    """Fetch A-share quote list from Eastmoney by pagination.

    Do not request pz=6000. Eastmoney often caps or rejects oversized pages; a
    paginated 200-row scan is slower but much more stable on Render.
    """
    if not target_codes:
        return {}
    url = "https://push2.eastmoney.com/api/qt/clist/get"
    result: dict[str, dict[str, Any]] = {}
    base_params = {
        "po": "1",
        "np": "1",
        "ut": "bd1d9ddb04089700cf9c27f6f7426281",
        "fltt": "2",
        "invt": "2",
        "fid": "f3",
        "fs": "m:0+t:6,m:0+t:80,m:1+t:2,m:1+t:23,m:0+t:81+s:2048",
        "fields": "f12,f13,f14,f2,f3,f4,f5,f6",
        "pz": "200",
    }
    for page in range(1, 45):
        params = dict(base_params, pn=str(page), _=str(int(time.time() * 1000)))
        payload = _http_get_json(url, params=params, timeout=8)
        diff = _extract_diff(payload)
        if not diff:
            break
        for item in diff:
            code = _clean_code(item.get("f12"))
            if not code or code not in target_codes:
                continue
            result[code] = {
                "name": str(item.get("f14") or "").strip(),
                "pct_change": _safe_float(item.get("f3")),
                "source": "eastmoney_clist",
            }
        if target_codes.issubset(result.keys()):
            break
    return result


def _fetch_sina_quote_map(records: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    """Fallback through Sina quote API. Provides name and computable pct change."""
    symbols: list[str] = []
    symbol_to_code: dict[str, str] = {}
    for record in records:
        code = _clean_code(record.get("code"))
        if not code:
            continue
        symbol = _market_symbol(code, str(record.get("market") or ""), "sina")
        if symbol and symbol not in symbol_to_code:
            symbols.append(symbol)
            symbol_to_code[symbol] = code
    if not symbols:
        return {}

    result: dict[str, dict[str, Any]] = {}
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        "Referer": "https://finance.sina.com.cn/",
    }
    for batch in _chunked(symbols, 50):
        url = "https://hq.sinajs.cn/list=" + ",".join(batch)
        try:
            response = _http_request("GET", url, headers=headers, timeout=8)
            raw = response.content.decode("gbk", errors="ignore") if getattr(response, "content", None) else response.text
        except Exception:
            continue
        for symbol, body in re.findall(r'var hq_str_([a-z]{2}\d{6})="(.*?)";', raw):
            code = symbol_to_code.get(symbol) or _clean_code(symbol)
            parts = body.split(",")
            if not code or len(parts) < 4 or not parts[0].strip():
                continue
            prev_close = _safe_float(parts[2])
            current = _safe_float(parts[3])
            pct_change = None
            if prev_close and current is not None and prev_close != 0:
                pct_change = round((current - prev_close) / prev_close * 100, 2)
            result[code] = {"name": parts[0].strip(), "pct_change": pct_change, "source": "sina"}
    return result


def _fetch_a_share_spot_map(target_codes: set[str] | None = None) -> dict[str, dict[str, Any]]:
    """Fetch one-shot A-share spot data through AkShare as a final fallback."""
    try:
        import akshare as ak

        df = ak.stock_zh_a_spot_em()
        if df is None or df.empty:
            return {}

        result: dict[str, dict[str, Any]] = {}
        for _, row in df.iterrows():
            code = _clean_code(row.get("代码") or row.get("code") or "")
            if not code:
                continue
            if target_codes and code not in target_codes:
                continue
            result[code] = {
                "name": str(row.get("名称") or row.get("股票简称") or row.get("name") or "").strip(),
                "pct_change": _safe_float(row.get("涨跌幅") or row.get("pct_change") or row.get("changePercent")),
                "source": "akshare_spot",
            }
            if target_codes and target_codes.issubset(result.keys()):
                break
        return result
    except Exception:
        return {}


def _merge_quote_maps(*maps: dict[str, dict[str, Any]]) -> dict[str, dict[str, Any]]:
    merged: dict[str, dict[str, Any]] = {}
    for source_map in maps:
        for code, quote in source_map.items():
            if not code:
                continue
            existing = merged.setdefault(code, {})
            if quote.get("name") and not existing.get("name"):
                existing["name"] = quote.get("name")
            if quote.get("pct_change") is not None and existing.get("pct_change") is None:
                existing["pct_change"] = quote.get("pct_change")
            if quote.get("source") and not existing.get("source"):
                existing["source"] = quote.get("source")
    return merged


def _get_quote_map(records: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    now = time.time()
    cached = _QUOTE_CACHE.get("data") or {}
    target_codes = {_clean_code(item.get("code")) for item in records if _clean_code(item.get("code"))}
    if cached and now < float(_QUOTE_CACHE.get("expires_at") or 0):
        if target_codes.issubset(set(cached.keys())):
            return {code: cached[code] for code in target_codes if code in cached}

    ulist_map = _fetch_eastmoney_ulist_map(records)
    missing_after_ulist = {code for code in target_codes if code not in ulist_map or not ulist_map.get(code, {}).get("name")}
    clist_map = _fetch_eastmoney_clist_map_for_codes(missing_after_ulist) if missing_after_ulist else {}
    merged = _merge_quote_maps(ulist_map, clist_map)

    missing_after_em = {code for code in target_codes if code not in merged or not merged.get(code, {}).get("name")}
    sina_map = _fetch_sina_quote_map([x for x in records if _clean_code(x.get("code")) in missing_after_em]) if missing_after_em else {}
    merged = _merge_quote_maps(merged, sina_map)

    missing_after_sina = {code for code in target_codes if code not in merged or not merged.get(code, {}).get("name")}
    ak_map = _fetch_a_share_spot_map(missing_after_sina) if missing_after_sina else {}
    merged = _merge_quote_maps(merged, ak_map)

    # Preserve successful quotes across requests.
    new_cache = dict(cached)
    new_cache.update({k: v for k, v in merged.items() if v})
    _QUOTE_CACHE["data"] = new_cache
    _QUOTE_CACHE["expires_at"] = now + QUOTE_TTL_SECONDS
    return merged


def _enrich_hot_stocks(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Enrich popularity records with real stock name and latest pct change."""
    if not records:
        return []

    quote_map = _get_quote_map(records)
    enriched: list[dict[str, Any]] = []
    for record in records:
        item = dict(record)
        code = _clean_code(item.get("code"))
        quote = quote_map.get(code) or {}
        quote_name = str(quote.get("name") or "").strip()
        current_name = str(item.get("name") or "").strip()
        if quote_name and (not current_name or current_name == code or current_name.isdigit()):
            item["name"] = quote_name
        elif not current_name:
            item["name"] = code
        if item.get("pct_change") is None and quote.get("pct_change") is not None:
            item["pct_change"] = quote.get("pct_change")
        if quote.get("source"):
            item["enrich_source"] = quote.get("source")
        enriched.append(item)
    return enriched


def _fetch_hot_rank_records(top_n: int) -> list[dict[str, Any]]:
    url = "https://emappdata.eastmoney.com/stockrank/getAllCurrentList"
    body = {"appId": "appId01", "globalId": "globalId", "pageNo": 1, "pageSize": max(top_n, 1)}
    payload = _http_post_json(url, body, timeout=10)
    records = _extract_record_list(payload)
    normalized: list[dict[str, Any]] = []
    seen: set[str] = set()
    for idx, item in enumerate(records, 1):
        record = _normalize_hot_record(item, idx)
        if not record:
            continue
        key = record.get("raw_code") or record.get("code")
        if key in seen:
            continue
        seen.add(str(key))
        normalized.append(record)
        if len(normalized) >= top_n:
            break
    return normalized


def _fetch_hot_rank_fallback_from_quotes(top_n: int) -> list[dict[str, Any]]:
    """If popularity endpoint is unavailable, return active A-share quotes as fallback.

    The label is still shown as hot stocks in the UI, but this fallback prevents
    an empty table during Eastmoney stockrank outages. Ranking is based on
    quote-list order sorted by pct change from Eastmoney.
    """
    quote_map = _fetch_eastmoney_clist_map_for_codes(set())
    if not quote_map:
        return []
    records = []
    for idx, (code, quote) in enumerate(list(quote_map.items())[:top_n], 1):
        market = _infer_market(code)
        records.append(
            {
                "rank": idx,
                "code": code,
                "name": quote.get("name") or code,
                "market": market,
                "raw_code": _market_symbol(code, market, "raw") or code,
                "pct_change": quote.get("pct_change"),
                "enrich_source": quote.get("source") or "quote_fallback",
            }
        )
    return records


def fetch_hot_stocks(top_n: int = 30, force_refresh: bool = False) -> list[dict[str, Any]]:
    """Fetch latest Eastmoney A-share popularity ranking.

    Returns stable fields for frontend:
    rank/code/name/raw_code/pct_change.  The popularity ranking endpoint is used
    only for rank + code, then quote data is enriched by Eastmoney ulist,
    Eastmoney paginated clist, Sina quote, and AkShare in sequence.
    """
    top_n = max(1, min(int(top_n or 30), 100))
    cache_key = f"hot:{top_n}"
    now = time.time()
    cache_data = _HOT_STOCKS_CACHE.get("data") or {}
    if not force_refresh and isinstance(cache_data, dict) and now < float(_HOT_STOCKS_CACHE.get("expires_at") or 0):
        cached_rows = cache_data.get(cache_key)
        if cached_rows:
            return cached_rows

    try:
        records = _fetch_hot_rank_records(top_n)
        enriched = _enrich_hot_stocks(records)
        # Keep rows even if enrichment partly fails; never discard valid hot rank codes.
        rows = enriched[:top_n]
    except Exception:
        rows = []

    # Cache partial success too, but for a shorter time if all names are missing.
    if rows:
        existing = cache_data if isinstance(cache_data, dict) else {}
        existing[cache_key] = rows
        any_enriched = any(str(x.get("name") or "") != str(x.get("code") or "") or x.get("pct_change") is not None for x in rows)
        _HOT_STOCKS_CACHE["data"] = existing
        _HOT_STOCKS_CACHE["expires_at"] = now + (HOT_STOCKS_TTL_SECONDS if any_enriched else 45)
    return rows


def debug_hot_stocks(top_n: int = 10) -> dict[str, Any]:
    """Diagnostic payload for Render/Vercel troubleshooting."""
    records = _fetch_hot_rank_records(top_n)
    quote_map = _get_quote_map(records)
    return {
        "rank_records_count": len(records),
        "rank_records_sample": records[:3],
        "quote_map_count": len(quote_map),
        "quote_map_sample": dict(list(quote_map.items())[:3]),
        "final_sample": _enrich_hot_stocks(records)[:top_n],
    }


def fetch_chart_data(stock_code: str, days: int = 60) -> dict[str, Any]:
    """Return kline and valuation data for frontend charts."""
    from graph.nodes import _fetch_recent_kline, _fetch_stock_basic, _fetch_valuation

    stock_code = str(stock_code).strip()
    try:
        kline_raw = _fetch_recent_kline(stock_code, days=days)
    except Exception:
        kline_raw = []
    try:
        valuation = _fetch_valuation(stock_code)
    except Exception:
        valuation = {}
    try:
        basic = _fetch_stock_basic(stock_code)
    except Exception:
        basic = {"股票代码": stock_code, "股票简称": stock_code}

    kline = []
    for item in kline_raw or []:
        kline.append(
            {
                "date": item.get("日期"),
                "close": _safe_float(item.get("收盘")),
                "pct_change": _safe_float(item.get("涨跌幅")),
                "volume": _safe_float(item.get("成交量")),
            }
        )

    return {
        "stock_code": stock_code,
        "stock_name": basic.get("股票简称", stock_code),
        "kline": kline,
        "valuation": valuation or {},
        "basic": basic or {},
    }
