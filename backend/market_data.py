"""Market data helpers used by the FastAPI bridge."""

from __future__ import annotations

from typing import Any


def _safe_float(value: Any) -> float | None:
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    text = str(value).strip().replace(",", "")
    if not text or text in {"-", "--", "N/A", "None", "nan"}:
        return None
    if text.endswith("%"):
        text = text[:-1]
    try:
        return float(text)
    except Exception:
        return None


def _first_value(item: dict[str, Any], keys: tuple[str, ...]) -> Any:
    for key in keys:
        value = item.get(key)
        if value not in (None, "", "--", "-"):
            return value
    return None


def _normalize_hot_record(item: dict[str, Any], index: int) -> dict[str, Any] | None:
    raw_code = (
        item.get("sc")
        or item.get("SECURITY_CODE")
        or item.get("securityCode")
        or item.get("code")
        or item.get("股票代码")
        or ""
    )
    raw_code = str(raw_code).strip().upper()

    market = str(item.get("market") or item.get("mkt") or "").strip().upper()
    code = raw_code
    if raw_code.startswith(("SH", "SZ", "BJ")):
        market = raw_code[:2]
        code = raw_code[2:]
    elif "." in raw_code:
        left, right = raw_code.split(".", 1)
        if left in {"SH", "SZ", "BJ"}:
            market, code = left, right
        else:
            code = right if right.isdigit() else left
    elif len(raw_code) == 6 and raw_code.isdigit():
        market = "SH" if raw_code.startswith("6") else "BJ" if raw_code.startswith(("8", "4")) else "SZ"
        code = raw_code

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
        "raw_code": raw_code or f"{market}{code}",
        "pct_change": pct_change,
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


def _http_get_json(url: str, params: dict[str, Any] | None = None, timeout: int = 8) -> Any:
    """GET JSON with curl_cffi first, then requests fallback."""
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        "Accept": "application/json,text/plain,*/*",
        "Referer": "https://quote.eastmoney.com/",
    }
    try:
        from curl_cffi import requests as cr

        response = cr.get(url, params=params, headers=headers, timeout=timeout, impersonate="chrome120")
    except Exception:
        import requests

        response = requests.get(url, params=params, headers=headers, timeout=timeout)
    if response.status_code != 200:
        return None
    text = response.text.strip()
    # Eastmoney occasionally returns JSONP-like payloads.
    if text and not text.startswith("{") and "(" in text and text.endswith(")"):
        text = text[text.find("(") + 1 : -1]
    try:
        return response.json()
    except Exception:
        import json

        return json.loads(text)


def _secid_for_code(code: str, market: str | None = None) -> str | None:
    """Build Eastmoney secid. SH uses 1.*, SZ/BJ usually use 0.*."""
    code = str(code or "").strip().zfill(6)
    if not code or len(code) != 6 or not code.isdigit():
        return None
    market = str(market or "").upper()
    prefix = "1" if market == "SH" or code.startswith("6") else "0"
    return f"{prefix}.{code}"


def _fetch_eastmoney_ulist_map(records: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    """Fetch exact quote data for the hot stock codes.

    This is more reliable than relying on the popularity-ranking payload, because
    that endpoint often only returns sc/rk and does not include name or pct change.
    """
    secids: list[str] = []
    for record in records:
        secid = _secid_for_code(str(record.get("code") or ""), str(record.get("market") or ""))
        if secid:
            secids.append(secid)
    if not secids:
        return {}

    url = "https://push2.eastmoney.com/api/qt/ulist.np/get"
    params = {
        "fltt": "2",
        "invt": "2",
        "fields": "f12,f14,f3",
        "secids": ",".join(secids[:100]),
    }
    try:
        payload = _http_get_json(url, params=params, timeout=8)
        diff = ((payload or {}).get("data") or {}).get("diff") or []
        result: dict[str, dict[str, Any]] = {}
        for item in diff:
            if not isinstance(item, dict):
                continue
            code = str(item.get("f12") or "").strip().zfill(6)
            if not code:
                continue
            result[code] = {
                "name": str(item.get("f14") or "").strip(),
                "pct_change": _safe_float(item.get("f3")),
            }
        return result
    except Exception:
        return {}


def _fetch_eastmoney_clist_map() -> dict[str, dict[str, Any]]:
    """Fetch broad A-share quote list from Eastmoney as a fallback."""
    url = "https://push2.eastmoney.com/api/qt/clist/get"
    params = {
        "pn": "1",
        "pz": "6000",
        "po": "1",
        "np": "1",
        "ut": "bd1d9ddb04089700cf9c27f6f7426281",
        "fltt": "2",
        "invt": "2",
        "fid": "f3",
        "fs": "m:0+t:6,m:0+t:80,m:1+t:2,m:1+t:23,m:0+t:81+s:2048",
        "fields": "f12,f14,f3",
    }
    try:
        payload = _http_get_json(url, params=params, timeout=10)
        diff = ((payload or {}).get("data") or {}).get("diff") or []
        result: dict[str, dict[str, Any]] = {}
        for item in diff:
            if not isinstance(item, dict):
                continue
            code = str(item.get("f12") or "").strip().zfill(6)
            if not code:
                continue
            result[code] = {
                "name": str(item.get("f14") or "").strip(),
                "pct_change": _safe_float(item.get("f3")),
            }
        return result
    except Exception:
        return {}


def _fetch_a_share_spot_map() -> dict[str, dict[str, Any]]:
    """Fetch one-shot A-share spot data through AkShare as a final fallback."""
    try:
        import akshare as ak

        df = ak.stock_zh_a_spot_em()
        if df is None or df.empty:
            return {}

        result: dict[str, dict[str, Any]] = {}
        for _, row in df.iterrows():
            code = str(row.get("代码") or row.get("code") or "").strip()
            if not code:
                continue
            code = code.zfill(6) if code.isdigit() else code
            result[code] = {
                "name": str(row.get("名称") or row.get("股票简称") or row.get("name") or "").strip(),
                "pct_change": _safe_float(row.get("涨跌幅") or row.get("pct_change") or row.get("changePercent")),
            }
        return result
    except Exception:
        return {}


def _enrich_hot_stocks(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Enrich popularity records with real stock name and latest pct change."""
    if not records:
        return []

    spot_map = _fetch_eastmoney_ulist_map(records)
    if not spot_map:
        spot_map = _fetch_eastmoney_clist_map()
    if not spot_map:
        spot_map = _fetch_a_share_spot_map()

    enriched: list[dict[str, Any]] = []
    for record in records:
        item = dict(record)
        code = str(item.get("code") or "").strip().zfill(6)
        spot = spot_map.get(code)
        if spot:
            spot_name = str(spot.get("name") or "").strip()
            if spot_name and (not item.get("name") or item.get("name") == item.get("code") or str(item.get("name")).isdigit()):
                item["name"] = spot_name
            if item.get("pct_change") is None:
                item["pct_change"] = spot.get("pct_change")
        enriched.append(item)
    return enriched


def fetch_hot_stocks(top_n: int = 30) -> list[dict[str, Any]]:
    """Fetch latest Eastmoney A-share popularity ranking with defensive parsing."""
    url = "https://emappdata.eastmoney.com/stockrank/getAllCurrentList"
    body = {"appId": "appId01", "globalId": "globalId", "pageNo": 1, "pageSize": max(top_n, 1)}
    headers = {
        "User-Agent": "Mozilla/5.0",
        "Accept": "application/json,text/plain,*/*",
        "Content-Type": "application/json",
    }

    try:
        try:
            from curl_cffi import requests as cr

            response = cr.post(url, json=body, headers=headers, timeout=10, impersonate="chrome120")
        except Exception:
            import requests

            response = requests.post(url, json=body, headers=headers, timeout=10)
        if response.status_code != 200:
            return []
        payload = response.json()
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
            seen.add(key)
            normalized.append(record)
            if len(normalized) >= top_n:
                break
        return _enrich_hot_stocks(normalized)
    except Exception:
        return []


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
