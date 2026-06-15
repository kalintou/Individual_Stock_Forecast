# capital_factor.py
from __future__ import annotations

import json
import math
import datetime as dt
from dataclasses import dataclass
from typing import Any, Optional

import pandas as pd

try:
    import akshare as ak
except Exception:  # pragma: no cover
    ak = None

try:
    from core.schemas import FactorEvidence
except Exception:
    # 兜底：方便单独测试 capital_factor.py
    @dataclass
    class FactorEvidence:
        factor_name: str
        trend_signal: str
        score: int
        key_findings: list[str]
        risk_flags: list[str]
        raw_data_summary: str


# =========================
# 基础工具函数
# =========================

def resolve_market(stock_code: str) -> str:
    """
    根据 A 股股票代码判断交易所：
    - sh: 上海证券交易所
    - sz: 深圳证券交易所
    - bj: 北京证券交易所
    """
    code = str(stock_code).strip().upper()
    code = code.replace(".SH", "").replace(".SZ", "").replace(".BJ", "")
    code = code.replace("SH", "").replace("SZ", "").replace("BJ", "")

    if len(code) != 6 or not code.isdigit():
        raise ValueError(f"Invalid A-share stock code: {stock_code}")

    # 上交所：主板 600/601/603/605，科创板 688/689
    if code.startswith(("600", "601", "603", "605", "688", "689")):
        return "sh"

    # 深交所：主板 000/001/002/003，创业板 300/301
    if code.startswith(("000", "001", "002", "003", "300", "301")):
        return "sz"

    # 北交所：常见 43/83/87/88/92 开头
    if code.startswith(("43", "83", "87", "88", "92")):
        return "bj"

    raise ValueError(f"Cannot resolve market for stock code: {stock_code}")


def _safe_float(x: Any, default: float = 0.0) -> float:
    if x is None:
        return default
    if isinstance(x, (int, float)):
        if math.isnan(x):
            return default
        return float(x)
    try:
        s = str(x).strip()
        s = s.replace(",", "")
        s = s.replace("%", "")
        if s in {"", "-", "--", "nan", "None"}:
            return default
        return float(s)
    except Exception:
        return default


def _find_col(df: pd.DataFrame, candidates: list[str]) -> Optional[str]:
    """
    在 AkShare 返回的中文列名中做模糊匹配。
    """
    if df is None or df.empty:
        return None

    cols = list(df.columns)

    # 完全匹配
    for c in candidates:
        if c in cols:
            return c

    # 去除空格、横线后的弱匹配
    normalized = {
        str(col).replace(" ", "").replace("-", "").replace("_", ""): col
        for col in cols
    }

    for cand in candidates:
        key = cand.replace(" ", "").replace("-", "").replace("_", "")
        if key in normalized:
            return normalized[key]

    # 包含匹配
    for cand in candidates:
        key = cand.replace(" ", "").replace("-", "").replace("_", "")
        for ncol, original_col in normalized.items():
            if key in ncol:
                return original_col

    return None


def _format_money_cn(value: float) -> str:
    """
    把金额格式化为中文可读形式。
    AkShare 资金流金额通常为“元”。
    """
    value = _safe_float(value)
    abs_v = abs(value)

    if abs_v >= 1e8:
        return f"{value / 1e8:.2f}亿元"
    if abs_v >= 1e4:
        return f"{value / 1e4:.2f}万元"
    return f"{value:.2f}元"

def _format_flow_direction(value: float, label: str = "主力资金") -> str:
    """
    把资金流金额转成自然语言方向表达。
    避免出现“净流入 -13.81亿元”这种不自然表述。
    """
    value = _safe_float(value)

    if value > 0:
        return f"{label}净流入 {_format_money_cn(value)}"
    elif value < 0:
        return f"{label}净流出 {_format_money_cn(abs(value))}"
    else:
        return f"{label}净流入为 0"

def _last_consecutive_count(values: list[float], positive: bool = True) -> int:
    """
    从最后一个交易日向前统计连续净流入/净流出天数。
    """
    count = 0
    for v in reversed(values):
        v = _safe_float(v)
        if positive and v > 0:
            count += 1
        elif not positive and v < 0:
            count += 1
        else:
            break
    return count


def _recent_weekdays(days: int = 20) -> list[str]:
    """
    生成最近若干个工作日日期字符串，格式 YYYYMMDD。
    用于尝试获取融资融券明细。
    """
    today = dt.date.today()
    results: list[str] = []
    offset = 0

    while len(results) < days:
        d = today - dt.timedelta(days=offset)
        if d.weekday() < 5:
            results.append(d.strftime("%Y%m%d"))
        offset += 1

    return results


# =========================
# AkShare 数据获取
# =========================

def fetch_capital_flow(stock_code: str, days: int = 20) -> pd.DataFrame:
    """
    获取个股资金流，所有容错逻辑均封装在本函数内，避免遗漏辅助函数。

    数据源顺序：
    1. 东方财富历史资金流接口（多个域名 + 重试）
    2. 东方财富单股实时资金快照接口
    3. 同花顺资金流接口（与东方财富不同的数据源）
    4. 本地最近成功缓存
    """
    import datetime as _dt
    import json as _json
    import os as _os
    import random as _random
    import time as _time
    from pathlib import Path as _Path

    code = str(stock_code).strip().upper()
    for suffix in (".SH", ".SZ", ".BJ", "SH", "SZ", "BJ"):
        code = code.replace(suffix, "")
    code = code[-6:]
    market = resolve_market(code)
    secid = f"{'1' if market == 'sh' else '0'}.{code}"
    limit = max(1, int(days))

    columns = [
        "日期", "收盘价", "涨跌幅",
        "主力净流入-净额", "主力净流入-净占比",
        "超大单净流入-净额", "超大单净流入-净占比",
        "大单净流入-净额", "大单净流入-净占比",
        "中单净流入-净额", "中单净流入-净占比",
        "小单净流入-净额", "小单净流入-净占比",
    ]
    errors: list[str] = []

    def _number(value: Any) -> float:
        if value is None:
            return 0.0
        if isinstance(value, (int, float)):
            try:
                return 0.0 if math.isnan(float(value)) else float(value)
            except Exception:
                return 0.0

        text = str(value).strip().replace(",", "").replace("%", "")
        if text in {"", "-", "--", "None", "nan"}:
            return 0.0

        multiplier = 1.0
        if text.endswith("万"):
            multiplier = 1e4
            text = text[:-1]
        elif text.endswith("亿"):
            multiplier = 1e8
            text = text[:-1]

        try:
            return float(text) * multiplier
        except Exception:
            return 0.0

    def _normalise(df: pd.DataFrame, source: str) -> pd.DataFrame:
        if df is None or df.empty:
            raise ValueError(f"{source} returned empty data")

        out = df.copy()
        for col in columns:
            if col not in out.columns:
                out[col] = 0.0

        out["日期"] = pd.to_datetime(out["日期"], errors="coerce")
        out = out.dropna(subset=["日期"]).sort_values("日期")
        if out.empty:
            raise ValueError(f"{source} returned no valid trade date")

        for col in columns[1:]:
            out[col] = out[col].map(_number)

        out = out[columns].tail(limit).reset_index(drop=True)
        out.attrs["data_source"] = source
        return out

    cache_dir = _Path(
        _os.getenv(
            "CAPITAL_CACHE_DIR",
            str(_Path(_os.getenv("TMPDIR", "/tmp")) / "stock_forecast_capital_cache"),
        )
    )
    cache_file = cache_dir / f"{code}.json"

    def _save_cache(df: pd.DataFrame) -> None:
        try:
            cache_dir.mkdir(parents=True, exist_ok=True)
            payload = {
                "saved_at": _dt.datetime.now(_dt.timezone.utc).isoformat(),
                "source": df.attrs.get("data_source", "unknown"),
                "records": df[columns].to_dict(orient="records"),
            }
            temp_file = cache_file.with_suffix(".tmp")
            temp_file.write_text(
                _json.dumps(payload, ensure_ascii=False, default=str),
                encoding="utf-8",
            )
            temp_file.replace(cache_file)
        except Exception:
            pass

    def _load_cache() -> pd.DataFrame:
        if not cache_file.exists():
            return pd.DataFrame()
        try:
            payload = _json.loads(cache_file.read_text(encoding="utf-8"))
            saved_at = _dt.datetime.fromisoformat(str(payload["saved_at"]))
            if saved_at.tzinfo is None:
                saved_at = saved_at.replace(tzinfo=_dt.timezone.utc)

            max_age = float(_os.getenv("CAPITAL_CACHE_MAX_AGE_HOURS", "168"))
            age = (
                _dt.datetime.now(_dt.timezone.utc) - saved_at
            ).total_seconds() / 3600
            if age > max_age:
                return pd.DataFrame()

            result = _normalise(
                pd.DataFrame(payload.get("records") or []),
                f"cache:{payload.get('source', 'unknown')}",
            )
            result.attrs["stale_cache"] = True
            return result
        except Exception:
            return pd.DataFrame()

    def _get_json(url: str, params: dict[str, Any]) -> dict[str, Any]:
        timeout = float(_os.getenv("CAPITAL_HTTP_TIMEOUT", "6"))
        headers = {
            "Accept": "application/json,text/plain,*/*",
            "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.7",
            "Connection": "close",
            "Referer": "https://data.eastmoney.com/",
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/124.0.0.0 Safari/537.36"
            ),
        }
        request_errors: list[str] = []

        try:
            from curl_cffi import requests as _curl_requests

            response = _curl_requests.get(
                url,
                params=params,
                headers=headers,
                timeout=timeout,
                impersonate="chrome",
            )
            response.raise_for_status()
            payload = response.json()
            if isinstance(payload, dict):
                return payload
            raise ValueError("response JSON is not an object")
        except Exception as exc:
            request_errors.append(f"curl_cffi: {type(exc).__name__}: {exc}")

        try:
            import requests as _requests

            session = _requests.Session()
            session.trust_env = False
            response = session.get(
                url,
                params=params,
                headers=headers,
                timeout=(3.05, timeout),
            )
            response.raise_for_status()
            payload = response.json()
            if isinstance(payload, dict):
                return payload
            raise ValueError("response JSON is not an object")
        except Exception as exc:
            request_errors.append(f"requests: {type(exc).__name__}: {exc}")

        raise RuntimeError("; ".join(request_errors))

    # 1. 东方财富历史资金流
    history_urls = [
        "https://push2his.eastmoney.com/api/qt/stock/fflow/daykline/get",
        "https://1.push2his.eastmoney.com/api/qt/stock/fflow/daykline/get",
        "https://push2.eastmoney.com/api/qt/stock/fflow/daykline/get",
    ]
    retries = max(1, int(_os.getenv("CAPITAL_FETCH_RETRIES", "3")))

    for attempt in range(retries):
        for url in history_urls:
            try:
                payload = _get_json(
                    url,
                    {
                        "lmt": str(max(20, limit)),
                        "klt": "101",
                        "secid": secid,
                        "fields1": "f1,f2,f3,f7",
                        "fields2": (
                            "f51,f52,f53,f54,f55,f56,f57,f58,f59,"
                            "f60,f61,f62,f63,f64,f65"
                        ),
                        "ut": "b2884a393a59ad64002292a3e90d46a5",
                        "_": int(_time.time() * 1000),
                    },
                )
                klines = (payload.get("data") or {}).get("klines") or []
                rows = []
                for item in klines:
                    parts = str(item).split(",")
                    if len(parts) >= 13:
                        rows.append(parts[:13])

                raw_columns = [
                    "日期",
                    "主力净流入-净额",
                    "小单净流入-净额",
                    "中单净流入-净额",
                    "大单净流入-净额",
                    "超大单净流入-净额",
                    "主力净流入-净占比",
                    "小单净流入-净占比",
                    "中单净流入-净占比",
                    "大单净流入-净占比",
                    "超大单净流入-净占比",
                    "收盘价",
                    "涨跌幅",
                ]
                result = _normalise(
                    pd.DataFrame(rows, columns=raw_columns),
                    "eastmoney_history",
                )
                _save_cache(result)
                return result
            except Exception as exc:
                errors.append(
                    f"history[{attempt + 1}] {url}: {type(exc).__name__}: {exc}"
                )

        if attempt + 1 < retries:
            _time.sleep(min(2.0, 0.4 * (2 ** attempt)) + _random.uniform(0.05, 0.2))

    # 2. 东方财富单股实时资金快照
    snapshot_urls = [
        "https://push2.eastmoney.com/api/qt/stock/get",
        "https://1.push2.eastmoney.com/api/qt/stock/get",
        "https://22.push2.eastmoney.com/api/qt/stock/get",
        "https://88.push2.eastmoney.com/api/qt/stock/get",
    ]
    snapshot_fields = "f57,f58,f43,f170,f62,f184,f66,f69,f72,f75,f78,f81,f84,f87,f124"

    for url in snapshot_urls:
        try:
            payload = _get_json(
                url,
                {
                    "secid": secid,
                    "fields": snapshot_fields,
                    "fltt": "2",
                    "invt": "2",
                    "ut": "fa5fd1943c7b386f172d6893dbfba10b",
                    "_": int(_time.time() * 1000),
                },
            )
            data = payload.get("data") or {}
            if str(data.get("f57", "")).zfill(6) != code:
                raise ValueError("snapshot stock code does not match")

            timestamp = _number(data.get("f124"))
            trade_date = (
                _dt.datetime.fromtimestamp(timestamp).date().isoformat()
                if timestamp > 0
                else _dt.date.today().isoformat()
            )
            result = _normalise(
                pd.DataFrame(
                    [{
                        "日期": trade_date,
                        "收盘价": data.get("f43", 0),
                        "涨跌幅": data.get("f170", 0),
                        "主力净流入-净额": data.get("f62", 0),
                        "主力净流入-净占比": data.get("f184", 0),
                        "超大单净流入-净额": data.get("f66", 0),
                        "超大单净流入-净占比": data.get("f69", 0),
                        "大单净流入-净额": data.get("f72", 0),
                        "大单净流入-净占比": data.get("f75", 0),
                        "中单净流入-净额": data.get("f78", 0),
                        "中单净流入-净占比": data.get("f81", 0),
                        "小单净流入-净额": data.get("f84", 0),
                        "小单净流入-净占比": data.get("f87", 0),
                    }]
                ),
                "eastmoney_snapshot",
            )
            _save_cache(result)
            return result
        except Exception as exc:
            errors.append(f"snapshot {url}: {type(exc).__name__}: {exc}")

    # 3. 独立备用源：同花顺。这里只在东方财富全部失败后执行。
    if ak is not None:
        for symbol in ("即时", "5日排行", "3日排行"):
            try:
                ths_df = ak.stock_fund_flow_individual(symbol=symbol)
                if ths_df is None or ths_df.empty:
                    continue

                code_col = _find_col(ths_df, ["股票代码", "代码"])
                if code_col is None:
                    continue

                matched = ths_df[
                    ths_df[code_col].astype(str).str.extract(r"(\d+)", expand=False).str.zfill(6) == code
                ]
                if matched.empty:
                    continue

                row = matched.iloc[0]
                price_col = _find_col(ths_df, ["最新价", "收盘价"])
                pct_col = _find_col(ths_df, ["涨跌幅", "阶段涨跌幅"])
                net_col = _find_col(ths_df, ["净额", "资金流入净额"])
                turnover_col = _find_col(ths_df, ["成交额"])

                net_amount = _number(row.get(net_col)) if net_col else 0.0
                turnover = _number(row.get(turnover_col)) if turnover_col else 0.0
                net_ratio = net_amount / turnover * 100 if turnover else 0.0

                result = _normalise(
                    pd.DataFrame(
                        [{
                            "日期": _dt.date.today().isoformat(),
                            "收盘价": row.get(price_col, 0) if price_col else 0,
                            "涨跌幅": row.get(pct_col, 0) if pct_col else 0,
                            "主力净流入-净额": net_amount,
                            "主力净流入-净占比": net_ratio,
                        }]
                    ),
                    f"ths_{symbol}",
                )
                _save_cache(result)
                return result
            except Exception as exc:
                errors.append(f"ths {symbol}: {type(exc).__name__}: {exc}")

    # 4. 在线源全部失败后读取最近一次成功缓存
    cached = _load_cache()
    if not cached.empty:
        return cached

    raise RuntimeError(
        f"Unable to obtain capital data for {code}; "
        + " | ".join(errors[-8:])
    )

def fetch_fund_flow_rank(stock_code: str, indicator: str = "5日") -> pd.DataFrame:
    """
    获取个股资金流排名数据。用 curl_cffi 直接调用东方财富 clist/get API，
    多 CDN 节点轮询，逐页搜索目标股票，找到即返回。
    indicator: "今日" / "3日" / "5日" / "10日"
    """
    import os
    import time
    import math

    os.environ.setdefault("NO_PROXY", "*")

    try:
        from curl_cffi import requests as cr
    except Exception:
        return pd.DataFrame()

    code = str(stock_code).strip()[-6:]

    indicator_map = {
        "今日": [
            "f62",
            "f12,f14,f2,f3,f62,f184,f66,f69,f72,f75,f78,f81,f84,f87,f204,f205,f124",
            [
                "排名", "代码", "名称", "最新价", "涨跌幅",
                "主力净流入-净额", "主力净流入-净占比",
                "超大单净流入-净额", "超大单净流入-净占比",
                "大单净流入-净额", "大单净流入-净占比",
                "中单净流入-净额", "中单净流入-净占比",
                "小单净流入-净额", "小单净流入-净占比",
            ],
        ],
        "3日": [
            "f267",
            "f12,f14,f2,f127,f267,f268,f269,f270,f271,f272,f273,f274,f275,f276,f257,f258,f124",
            [
                "排名", "代码", "名称", "最新价", "3日涨跌幅",
                "3日主力净流入-净额", "3日主力净流入-净占比",
                "3日超大单净流入-净额", "3日超大单净流入-净占比",
                "3日大单净流入-净额", "3日大单净流入-净占比",
                "3日中单净流入-净额", "3日中单净流入-净占比",
                "3日小单净流入-净额", "3日小单净流入-净占比",
            ],
        ],
        "5日": [
            "f164",
            "f12,f14,f2,f109,f164,f165,f166,f167,f168,f169,f170,f171,f172,f173,f257,f258,f124",
            [
                "排名", "代码", "名称", "最新价", "5日涨跌幅",
                "5日主力净流入-净额", "5日主力净流入-净占比",
                "5日超大单净流入-净额", "5日超大单净流入-净占比",
                "5日大单净流入-净额", "5日大单净流入-净占比",
                "5日中单净流入-净额", "5日中单净流入-净占比",
                "5日小单净流入-净额", "5日小单净流入-净占比",
            ],
        ],
        "10日": [
            "f174",
            "f12,f14,f2,f160,f174,f175,f176,f177,f178,f179,f180,f181,f182,f183,f260,f261,f124",
            [
                "排名", "代码", "名称", "最新价", "10日涨跌幅",
                "10日主力净流入-净额", "10日主力净流入-净占比",
                "10日超大单净流入-净额", "10日超大单净流入-净占比",
                "10日大单净流入-净额", "10日大单净流入-净占比",
                "10日中单净流入-净额", "10日中单净流入-净占比",
                "10日小单净流入-净额", "10日小单净流入-净占比",
            ],
        ],
    }

    if indicator not in indicator_map:
        indicator = "5日"

    fid, fields, columns = indicator_map[indicator]
    params = {
        "fid": fid,
        "po": "1",
        "pz": "100",
        "pn": "1",
        "np": "1",
        "fltt": "2",
        "invt": "2",
        "ut": "b2884a393a59ad64002292a3e90d46a5",
        "fs": "m:0+t:6+f:!2,m:0+t:13+f:!2,m:0+t:80+f:!2,m:1+t:2+f:!2,m:1+t:23+f:!2,m:0+t:7+f:!2,m:1+t:3+f:!2",
        "fields": fields,
    }

    domains = [
        "push2.eastmoney.com",
        "1.push2.eastmoney.com",
        "11.push2.eastmoney.com",
        "22.push2.eastmoney.com",
        "33.push2.eastmoney.com",
        "44.push2.eastmoney.com",
        "55.push2.eastmoney.com",
        "66.push2.eastmoney.com",
        "77.push2.eastmoney.com",
        "88.push2.eastmoney.com",
        "99.push2.eastmoney.com",
    ]

    for domain in domains:
        try:
            url = f"https://{domain}/api/qt/clist/get"

            # 获取第一页
            r = cr.get(url, params=params, timeout=15, impersonate="chrome120")
            if r.status_code != 200:
                continue
            data = r.json()
            total = data.get("data", {}).get("total", 0)
            if not total:
                continue

            per_page = 100
            max_pages = min(25, math.ceil(total / per_page))

            # 逐页搜索目标股票
            for page in range(1, max_pages + 1):
                if page > 1:
                    time.sleep(0.3)
                    params["pn"] = page
                    r = cr.get(url, params=params, timeout=15, impersonate="chrome120")
                    if r.status_code != 200:
                        break
                    data = r.json()

                diffs = data.get("data", {}).get("diff", [])
                for idx, item in enumerate(diffs):
                    if str(item.get("f12", "")).zfill(6) == code:
                        # 找到目标股票，构造 DataFrame
                        rank = (page - 1) * per_page + idx + 1
                        row = {"排名": rank}
                        row.update(item)
                        df = pd.DataFrame([row])
                        # 列名映射：按字段顺序重命名
                        field_list = fields.split(",")
                        rename_map = {}
                        for i, fld in enumerate(field_list):
                            if i < len(columns) - 1:  # -1 because "排名" is already added
                                rename_map[fld] = columns[i + 1]
                        df.rename(columns=rename_map, inplace=True)
                        df["排名"] = rank
                        # 只保留需要的列
                        available_cols = [c for c in columns if c in df.columns]
                        return df[available_cols]

            # 搜完了也没找到
            return pd.DataFrame()
        except Exception:
            pass
        time.sleep(0.2)

    # ========== 降级：排名API被封时，用单股历史流向数据构造等效输出 ==========
    if ak is not None:
        try:
            df = ak.stock_individual_fund_flow(stock=code, market="sh")
            if df is None or df.empty:
                df = ak.stock_individual_fund_flow(stock=code, market="sz")
            if df is not None and not df.empty:
                days = {"今日": 1, "3日": 3, "5日": 5, "10日": 10}.get(indicator, 5)
                recent = df.head(days)
                latest = df.iloc[0]

                prefix = "" if indicator == "今日" else indicator
                result = {
                    "代码": code,
                    "名称": latest.get("股票名称", code),
                    "最新价": latest.get("收盘价", latest.get("最新价", "N/A")),
                    f"{prefix}涨跌幅" if prefix else "涨跌幅": "N/A",
                    f"{prefix}主力净流入-净额": recent["主力净流入-净额"].sum() if "主力净流入-净额" in recent.columns else "N/A",
                    f"{prefix}主力净流入-净占比": recent["主力净流入-净占比"].mean() if "主力净流入-净占比" in recent.columns else "N/A",
                    f"{prefix}超大单净流入-净额": recent["超大单净流入-净额"].sum() if "超大单净流入-净额" in recent.columns else "N/A",
                    f"{prefix}超大单净流入-净占比": recent["超大单净流入-净占比"].mean() if "超大单净流入-净占比" in recent.columns else "N/A",
                    f"{prefix}大单净流入-净额": recent["大单净流入-净额"].sum() if "大单净流入-净额" in recent.columns else "N/A",
                    f"{prefix}大单净流入-净占比": recent["大单净流入-净占比"].mean() if "大单净流入-净占比" in recent.columns else "N/A",
                    f"{prefix}中单净流入-净额": recent["中单净流入-净额"].sum() if "中单净流入-净额" in recent.columns else "N/A",
                    f"{prefix}中单净流入-净占比": recent["中单净流入-净占比"].mean() if "中单净流入-净占比" in recent.columns else "N/A",
                    f"{prefix}小单净流入-净额": recent["小单净流入-净额"].sum() if "小单净流入-净额" in recent.columns else "N/A",
                    f"{prefix}小单净流入-净占比": recent["小单净流入-净占比"].mean() if "小单净流入-净占比" in recent.columns else "N/A",
                }
                return pd.DataFrame([result])
        except Exception:
            pass

    return pd.DataFrame()



def fetch_margin_data(stock_code: str, lookback_days: int = 15) -> pd.DataFrame:
    """
    获取融资融券明细数据。

    注意：
    - 融资融券不是所有股票都有。
    - 北交所或部分股票可能没有数据。
    - AkShare 接口偶尔会因为交易日、网络、源站限制失败。
    所以这里始终做成“可选增强数据”，失败时返回空 DataFrame。
    """
    if ak is None:
        return pd.DataFrame()

    code = str(stock_code).strip()[-6:]

    try:
        market = resolve_market(code)
    except Exception:
        return pd.DataFrame()

    if market == "bj":
        return pd.DataFrame()

    rows: list[pd.DataFrame] = []

    for date_str in _recent_weekdays(lookback_days):
        try:
            if market == "sh":
                df = ak.stock_margin_detail_sse(date=date_str)
            elif market == "sz":
                df = ak.stock_margin_detail_szse(date=date_str)
            else:
                continue

            if df is None or df.empty:
                continue

            code_col = _find_col(df, ["证券代码", "股票代码", "代码"])
            if code_col is None:
                continue

            tmp = df[df[code_col].astype(str).str.zfill(6) == code].copy()
            if tmp.empty:
                continue

            tmp["__date"] = pd.to_datetime(date_str, format="%Y%m%d", errors="coerce")
            rows.append(tmp)

            # 拿到最近 5 条即可
            if len(rows) >= 5:
                break

        except Exception:
            continue

    if not rows:
        return pd.DataFrame()

    result = pd.concat(rows, ignore_index=True)
    result = result.sort_values("__date").reset_index(drop=True)
    return result


# =========================
# 指标计算
# =========================

def calculate_capital_indicators(
    flow_df: pd.DataFrame,
    margin_df: Optional[pd.DataFrame] = None,
    rank_df: Optional[pd.DataFrame] = None,
) -> dict[str, Any]:
    """根据实际拿到的数据量计算资金指标，不用单日快照冒充 3 日/5 日历史。"""
    indicators: dict[str, Any] = {
        "data_available": False,
        "data_quality": "empty",
        "data_source": "unknown",
        "stale_cache": False,
        "latest_trade_date": None,
        "raw_rows": 0,
        "history_days": 0,
        "has_3d_history": False,
        "has_5d_history": False,

        "latest_main_net_inflow": 0.0,
        "latest_main_net_inflow_ratio": None,
        "main_net_inflow_3d_sum": None,
        "main_net_inflow_5d_sum": None,
        "main_net_inflow_5d_mean": None,
        "main_net_inflow_ratio_5d_mean": None,

        "latest_super_large_net_inflow": None,
        "latest_large_net_inflow": None,
        "latest_medium_net_inflow": None,
        "latest_small_net_inflow": None,
        "flow_level_detail_available": False,

        "consecutive_inflow_days": 0,
        "consecutive_outflow_days": 0,
        "main_small_divergence": False,
        "accumulation_signal": False,
        "retail_chasing_risk": False,
        "abnormal_large_inflow": False,
        "abnormal_large_outflow": False,

        "latest_pct_change": None,
        "price_fund_divergence": False,

        "rank_available": False,
        "fund_flow_rank_summary": None,
        "margin_available": False,
        "margin_balance_latest": None,
        "margin_balance_change_rate": None,
        "margin_buy_latest": None,
        "margin_buy_active_ratio": None,

        "warnings": [],
        "data_notes": [],
    }

    if flow_df is None or flow_df.empty:
        indicators["warnings"].append("个股资金流数据为空")
        return indicators

    # attrs 必须在 copy 之前读取，避免不同 pandas 版本丢失 attrs。
    indicators["data_source"] = str(flow_df.attrs.get("data_source", "unknown"))
    indicators["stale_cache"] = bool(flow_df.attrs.get("stale_cache", False))

    df = flow_df.copy()
    indicators["data_available"] = True

    date_col = _find_col(df, ["日期", "date"])
    main_amt_col = _find_col(df, [
        "主力净流入-净额", "主力净流入净额", "主力净流入", "主力净额",
    ])
    main_ratio_col = _find_col(df, [
        "主力净流入-净占比", "主力净流入净占比", "主力净占比",
    ])
    super_amt_col = _find_col(df, [
        "超大单净流入-净额", "超大单净流入净额", "超大单净流入",
    ])
    large_amt_col = _find_col(df, [
        "大单净流入-净额", "大单净流入净额", "大单净流入",
    ])
    medium_amt_col = _find_col(df, [
        "中单净流入-净额", "中单净流入净额", "中单净流入",
    ])
    small_amt_col = _find_col(df, [
        "小单净流入-净额", "小单净流入净额", "小单净流入",
    ])
    pct_col = _find_col(df, ["涨跌幅", "涨跌幅%", "pct_chg", "涨跌幅度"])

    if main_amt_col is None:
        indicators["data_quality"] = "missing_main_flow_column"
        indicators["warnings"].append("缺少主力净流入金额字段")
        return indicators

    if date_col:
        df[date_col] = pd.to_datetime(df[date_col], errors="coerce")
        df = df.dropna(subset=[date_col]).sort_values(date_col)

    if df.empty:
        indicators["data_available"] = False
        indicators["warnings"].append("资金流数据没有有效交易日期")
        return indicators

    indicators["raw_rows"] = len(df)
    indicators["history_days"] = len(df)
    indicators["has_3d_history"] = len(df) >= 3
    indicators["has_5d_history"] = len(df) >= 5

    if len(df) >= 5:
        indicators["data_quality"] = "full_history"
    elif len(df) >= 3:
        indicators["data_quality"] = "partial_history"
        indicators["data_notes"].append("当前不足5个交易日，仅计算最新和近3日指标")
    else:
        indicators["data_quality"] = "snapshot"
        indicators["data_notes"].append(
            f"当前仅获得{len(df)}个交易日数据，不计算近3日和近5日趋势"
        )

    if indicators["stale_cache"]:
        indicators["warnings"].append("在线数据源暂不可用，本次使用最近成功缓存")

    main_values = [_safe_float(x) for x in df[main_amt_col].tolist()]
    latest = df.iloc[-1]

    if date_col:
        latest_date = latest[date_col]
        indicators["latest_trade_date"] = (
            str(latest_date.date()) if hasattr(latest_date, "date") else str(latest_date)
        )

    latest_main = _safe_float(latest[main_amt_col])
    indicators["latest_main_net_inflow"] = latest_main

    if main_ratio_col:
        indicators["latest_main_net_inflow_ratio"] = _safe_float(latest[main_ratio_col])

    if indicators["has_3d_history"]:
        indicators["main_net_inflow_3d_sum"] = float(sum(main_values[-3:]))

    if indicators["has_5d_history"]:
        last5 = main_values[-5:]
        indicators["main_net_inflow_5d_sum"] = float(sum(last5))
        indicators["main_net_inflow_5d_mean"] = float(sum(last5) / 5)

        if main_ratio_col:
            ratio_values = [_safe_float(x) for x in df[main_ratio_col].tolist()]
            indicators["main_net_inflow_ratio_5d_mean"] = float(sum(ratio_values[-5:]) / 5)

    source = indicators["data_source"].lower()
    # 同花顺备用接口通常只有主力净额，没有完整的超大单/大单/中单/小单拆分。
    level_detail_expected = "ths_" not in source

    if level_detail_expected and super_amt_col and large_amt_col and medium_amt_col and small_amt_col:
        indicators["latest_super_large_net_inflow"] = _safe_float(latest[super_amt_col])
        indicators["latest_large_net_inflow"] = _safe_float(latest[large_amt_col])
        indicators["latest_medium_net_inflow"] = _safe_float(latest[medium_amt_col])
        indicators["latest_small_net_inflow"] = _safe_float(latest[small_amt_col])
        indicators["flow_level_detail_available"] = True

    indicators["consecutive_inflow_days"] = _last_consecutive_count(main_values, positive=True)
    indicators["consecutive_outflow_days"] = _last_consecutive_count(main_values, positive=False)

    small_flow = indicators.get("latest_small_net_inflow")
    if small_flow is not None:
        small_flow = _safe_float(small_flow)
        indicators["main_small_divergence"] = latest_main * small_flow < 0
        indicators["accumulation_signal"] = latest_main > 0 and small_flow < 0
        indicators["retail_chasing_risk"] = latest_main < 0 and small_flow > 0

    if indicators["has_5d_history"]:
        last5 = main_values[-5:]
        mean5 = sum(last5) / 5
        std5 = pd.Series(last5).std()
        if std5 and not math.isnan(std5):
            indicators["abnormal_large_inflow"] = latest_main > mean5 + 1.5 * std5 and latest_main > 0
            indicators["abnormal_large_outflow"] = latest_main < mean5 - 1.5 * std5 and latest_main < 0

    if pct_col:
        latest_pct = _safe_float(latest[pct_col])
        indicators["latest_pct_change"] = latest_pct
        indicators["price_fund_divergence"] = latest_pct > 1.0 and latest_main < 0

    if rank_df is not None and not rank_df.empty:
        indicators["rank_available"] = True
        indicators["fund_flow_rank_summary"] = {
            str(k): str(v) for k, v in rank_df.iloc[0].to_dict().items() if k is not None
        }

    if margin_df is not None and not margin_df.empty:
        margin = margin_df.copy()
        margin_balance_col = _find_col(margin, ["融资余额", "融资余额(元)", "融资余额（元）"])
        margin_buy_col = _find_col(margin, ["融资买入额", "融资买入额(元)", "融资买入额（元）"])

        if margin_balance_col:
            indicators["margin_available"] = True
            balances = [_safe_float(x) for x in margin[margin_balance_col].tolist()]
            indicators["margin_balance_latest"] = balances[-1]
            if len(balances) >= 2 and abs(balances[-2]) > 1e-9:
                indicators["margin_balance_change_rate"] = (
                    (balances[-1] - balances[-2]) / abs(balances[-2]) * 100
                )

        if margin_buy_col:
            latest_buy = _safe_float(margin.iloc[-1][margin_buy_col])
            indicators["margin_buy_latest"] = latest_buy
            latest_balance = indicators.get("margin_balance_latest")
            if latest_balance is not None and abs(_safe_float(latest_balance)) > 1e-9:
                indicators["margin_buy_active_ratio"] = (
                    latest_buy / abs(_safe_float(latest_balance)) * 100
                )

    return indicators

def score_capital_factor(indicators: dict[str, Any]) -> dict[str, Any]:
    """按实际可用周期评分；没有历史数据时不虚构 3 日/5 日信号。"""
    score = 50
    key_findings: list[str] = []
    risk_flags: list[str] = []

    if not indicators.get("data_available"):
        return {
            "score": 50,
            "trend_signal": "Neutral",
            "key_findings": ["资金流数据不可用，资金因子暂按中性处理。"],
            "risk_flags": ["资金流数据缺失，资金面分析置信度下降。"],
        }

    latest_main = _safe_float(indicators.get("latest_main_net_inflow"))
    latest_ratio_raw = indicators.get("latest_main_net_inflow_ratio")
    latest_ratio = _safe_float(latest_ratio_raw) if latest_ratio_raw is not None else None
    has_3d = bool(indicators.get("has_3d_history"))
    has_5d = bool(indicators.get("has_5d_history"))
    inflow_days = int(indicators.get("consecutive_inflow_days") or 0)
    outflow_days = int(indicators.get("consecutive_outflow_days") or 0)

    if latest_main > 0:
        score += 8
        text = f"最近一个交易日主力资金净流入 {_format_money_cn(latest_main)}"
        if latest_ratio is not None:
            text += f"，净流入占比 {latest_ratio:.2f}%"
        key_findings.append(text + "。")
    elif latest_main < 0:
        score -= 8
        text = f"最近一个交易日主力资金净流出 {_format_money_cn(abs(latest_main))}"
        if latest_ratio is not None:
            text += f"，净流入占比 {latest_ratio:.2f}%"
        key_findings.append(text + "。")
    else:
        key_findings.append("最近一个交易日主力资金净额接近 0，单日方向不明显。")

    # 单日快照也可以用当日净占比判断强弱，但权重低于完整 5 日均值。
    if not has_5d and latest_ratio is not None:
        if latest_ratio >= 5:
            score += 5
            key_findings.append(f"当日主力净流入占比达到 {latest_ratio:.2f}%，单日流入力度较强。")
        elif latest_ratio <= -5:
            score -= 5
            risk_flags.append(f"当日主力净流入占比为 {latest_ratio:.2f}%，单日流出压力较大。")

    if has_3d:
        sum3 = _safe_float(indicators.get("main_net_inflow_3d_sum"))
        if sum3 > 0:
            score += 5
            key_findings.append(f"近3日主力资金合计净流入 {_format_money_cn(sum3)}。")
        elif sum3 < 0:
            score -= 5
            risk_flags.append(f"近3日主力资金合计净流出 {_format_money_cn(abs(sum3))}。")

    if has_5d:
        sum5 = _safe_float(indicators.get("main_net_inflow_5d_sum"))
        ratio5 = _safe_float(indicators.get("main_net_inflow_ratio_5d_mean"))
        if sum5 > 0:
            score += 6
            key_findings.append(f"近5日主力资金合计净流入 {_format_money_cn(sum5)}。")
        elif sum5 < 0:
            score -= 6
            risk_flags.append(f"近5日主力资金合计净流出 {_format_money_cn(abs(sum5))}。")

        if ratio5 >= 5:
            score += 12
            key_findings.append(f"近5日主力净流入占比均值为 {ratio5:.2f}%，持续流入力度较高。")
        elif ratio5 >= 2:
            score += 6
            key_findings.append(f"近5日主力净流入占比均值为 {ratio5:.2f}%，资金面偏积极。")
        elif ratio5 <= -5:
            score -= 12
            risk_flags.append(f"近5日主力净流入占比均值为 {ratio5:.2f}%，持续撤离迹象较明显。")
        elif ratio5 <= -2:
            score -= 6
            risk_flags.append(f"近5日主力净流入占比均值为 {ratio5:.2f}%，资金面偏弱。")

    # 连续性至少需要 2 个交易日才有解释意义。
    if inflow_days >= 3:
        score += 10
        key_findings.append(f"主力资金已连续 {inflow_days} 个交易日净流入，持续性较好。")
    elif inflow_days == 2:
        score += 5
        key_findings.append("主力资金连续 2 个交易日净流入，短期资金面改善。")

    if outflow_days >= 3:
        score -= 12
        risk_flags.append(f"主力资金已连续 {outflow_days} 个交易日净流出，存在持续撤离风险。")
    elif outflow_days == 2:
        score -= 6
        risk_flags.append("主力资金连续 2 个交易日净流出，短期资金面偏弱。")

    if indicators.get("flow_level_detail_available"):
        super_flow = _safe_float(indicators.get("latest_super_large_net_inflow"))
        large_flow = _safe_float(indicators.get("latest_large_net_inflow"))
        medium_flow = _safe_float(indicators.get("latest_medium_net_inflow"))
        small_flow = _safe_float(indicators.get("latest_small_net_inflow"))

        if indicators.get("accumulation_signal"):
            score += 10
            key_findings.append(
                f"主力净流入而小单净流出 {_format_money_cn(abs(small_flow))}，资金结构呈现吸筹特征。"
            )
        if indicators.get("retail_chasing_risk"):
            score -= 12
            risk_flags.append(
                f"主力净流出而小单净流入 {_format_money_cn(small_flow)}，存在散户承接抛压风险。"
            )

        if super_flow > 0 and large_flow > 0:
            key_findings.append(
                f"超大单净流入 {_format_money_cn(super_flow)}、大单净流入 {_format_money_cn(large_flow)}，大资金方向一致偏强。"
            )
        elif super_flow < 0 and large_flow < 0:
            risk_flags.append(
                f"超大单净流出 {_format_money_cn(abs(super_flow))}、大单净流出 {_format_money_cn(abs(large_flow))}，大资金方向一致偏弱。"
            )
        elif (super_flow > 0 > large_flow) or (large_flow > 0 > super_flow):
            key_findings.append("超大单与大单方向相反，大资金内部存在分歧。")

        if medium_flow > 0 and super_flow < 0 and large_flow < 0:
            risk_flags.append("中单流入但超大单和大单流出，资金层级分歧明显。")

    if indicators.get("abnormal_large_inflow"):
        score += 8
        key_findings.append("最新主力净流入显著高于近5日波动水平，出现异常流入。")
    if indicators.get("abnormal_large_outflow"):
        score -= 10
        risk_flags.append("最新主力净流出显著高于近5日波动水平，出现异常流出。")
    if indicators.get("price_fund_divergence"):
        score -= 6
        risk_flags.append("股价上涨但主力资金净流出，价格与资金方向背离。")

    # 排名和融资融券只有真正拿到时才参与；缺失不再作为每只股票共同的风险文案。
    rank_summary = indicators.get("fund_flow_rank_summary")
    if isinstance(rank_summary, dict):
        rank_amt = _safe_float(rank_summary.get("5日主力净流入-净额"))
        rank_ratio = _safe_float(rank_summary.get("5日主力净流入-净占比"))
        if rank_amt > 0 and rank_ratio >= 5:
            score += 3
            key_findings.append(f"横向排名数据确认近5日主力净流入占比为 {rank_ratio:.2f}%。")
        elif rank_amt < 0 and rank_ratio <= -5:
            score -= 3
            risk_flags.append(f"横向排名数据确认近5日主力净流入占比为 {rank_ratio:.2f}%。")

    if indicators.get("margin_available"):
        margin_change = indicators.get("margin_balance_change_rate")
        if margin_change is not None:
            margin_change = _safe_float(margin_change)
            if margin_change > 3 and latest_main > 0:
                score += 5
                key_findings.append(f"融资余额环比上升 {margin_change:.2f}%，与主力流入形成共振。")
            elif margin_change > 5 and latest_main < 0:
                score -= 5
                risk_flags.append(f"融资余额环比上升 {margin_change:.2f}%，但主力流出，存在杠杆追高风险。")
            elif margin_change < -3:
                score -= 3
                risk_flags.append(f"融资余额环比下降 {abs(margin_change):.2f}%，杠杆参与度下降。")

    if indicators.get("stale_cache"):
        score -= 2
        risk_flags.append("本次使用最近成功缓存，数据时效性低于在线实时数据。")

    if not has_3d:
        key_findings.append(
            f"当前数据源仅提供 {int(indicators.get('history_days') or 0)} 个交易日，未生成近3日/近5日趋势结论。"
        )
    elif not has_5d:
        key_findings.append("当前历史数据不足5个交易日，未生成近5日趋势结论。")

    score = int(round(score))
    severe = bool(
        indicators.get("retail_chasing_risk")
        or indicators.get("abnormal_large_outflow")
        or indicators.get("price_fund_divergence")
    )
    if score < 20 and not severe:
        score = 20
    score = max(0, min(100, score))

    trend_signal = "Bullish" if score >= 60 else "Neutral" if score >= 40 else "Bearish"
    key_findings = list(dict.fromkeys(key_findings))[:7]
    risk_flags = list(dict.fromkeys(risk_flags))[:6]

    return {
        "score": score,
        "trend_signal": trend_signal,
        "key_findings": key_findings,
        "risk_flags": risk_flags,
    }

def build_capital_prompt_data(indicators: dict[str, Any]) -> str:
    """
    构造给 LLM 的结构化资金因子数据。
    """
    scored = score_capital_factor(indicators)

    payload = {
        "capital_indicators": indicators,
        "rule_based_result": scored,
        "anti_hallucination_constraints": [
            "只能基于 capital_indicators 和 rule_based_result 解释。",
            "没有机构持仓数据时，不得声称机构加仓或减仓。",
            "没有龙虎榜数据时，不得声称游资买入或卖出。",
            "没有大宗交易数据时，不得声称大宗交易活跃。",
            "融资融券数据不可用时，不得声称融资资金明显流入或流出。",
            "不得修改规则评分生成的 score 和 trend_signal。",
        ],
    }

    return json.dumps(payload, ensure_ascii=False, indent=2, default=str)


def build_raw_data_summary(indicators: dict[str, Any]) -> str:
    """生成完全由实际资金数据驱动的摘要，不由 LLM 覆盖。"""
    if not indicators.get("data_available"):
        return "个股资金流数据不可用，资金因子暂按中性处理。"

    source = str(indicators.get("data_source") or "unknown")
    source_lower = source.lower()
    if source_lower.startswith("cache:"):
        source_name = "本地最近成功缓存"
    elif "eastmoney_history" in source_lower:
        source_name = "东方财富历史资金流"
    elif "eastmoney_snapshot" in source_lower:
        source_name = "东方财富实时资金快照"
    elif "ths_" in source_lower:
        source_name = "同花顺备用资金流"
    else:
        source_name = source

    rows = int(indicators.get("history_days") or indicators.get("raw_rows") or 0)
    date = indicators.get("latest_trade_date")
    head = f"数据源为{source_name}，实际获得 {rows} 个交易日"
    if date:
        head += f"，最新交易日为 {date}"

    parts = [head]

    latest_main = _safe_float(indicators.get("latest_main_net_inflow"))
    latest_ratio_raw = indicators.get("latest_main_net_inflow_ratio")
    latest_text = f"最近一日{_format_flow_direction(latest_main)}"
    if latest_ratio_raw is not None:
        latest_text += f"，净流入占比 {_safe_float(latest_ratio_raw):.2f}%"
    parts.append(latest_text)

    if indicators.get("has_3d_history"):
        parts.append(
            f"近3日{_format_flow_direction(indicators.get('main_net_inflow_3d_sum'), '主力资金合计')}"
        )
    else:
        parts.append("因历史样本不足3日，未计算近3日主力趋势")

    if indicators.get("has_5d_history"):
        parts.append(
            f"近5日{_format_flow_direction(indicators.get('main_net_inflow_5d_sum'), '主力资金合计')}"
        )
        parts.append(
            f"近5日主力净流入占比均值 {_safe_float(indicators.get('main_net_inflow_ratio_5d_mean')):.2f}%"
        )
    else:
        parts.append("因历史样本不足5日，未计算近5日主力趋势")

    if indicators.get("flow_level_detail_available"):
        parts.append(
            "最近一日分单结构为："
            f"{_format_flow_direction(indicators.get('latest_super_large_net_inflow'), '超大单资金')}，"
            f"{_format_flow_direction(indicators.get('latest_large_net_inflow'), '大单资金')}，"
            f"{_format_flow_direction(indicators.get('latest_medium_net_inflow'), '中单资金')}，"
            f"{_format_flow_direction(indicators.get('latest_small_net_inflow'), '小单资金')}"
        )
    else:
        parts.append("当前备用数据源未提供完整的超大单、大单、中单和小单拆分")

    latest_pct = indicators.get("latest_pct_change")
    if latest_pct is not None:
        parts.append(f"最近一日涨跌幅为 {_safe_float(latest_pct):.2f}%")

    inflow_days = int(indicators.get("consecutive_inflow_days") or 0)
    outflow_days = int(indicators.get("consecutive_outflow_days") or 0)
    if inflow_days >= 2:
        parts.append(f"主力资金连续 {inflow_days} 个交易日净流入")
    elif outflow_days >= 2:
        parts.append(f"主力资金连续 {outflow_days} 个交易日净流出")

    if indicators.get("price_fund_divergence"):
        parts.append("股价上涨但主力净流出，存在价格—资金背离")
    if indicators.get("stale_cache"):
        parts.append("在线源失败，本次使用缓存数据，需注意时效性")

    return "；".join(parts) + "。"

def build_capital_evidence(
    stock_name: str,
    stock_code: str,
    indicators: dict[str, Any],
    llm_result: Optional[dict[str, Any]] = None,
) -> FactorEvidence:
    """
    构造资金证据。

    资金面属于强结构化数值分析：规则结果和实际数据摘要是事实主干，
    LLM 不得覆盖 key_findings、risk_flags 或 raw_data_summary，避免不同股票被写成同一模板。
    参数 llm_result 仅为兼容旧调用保留。
    """
    scored = score_capital_factor(indicators)
    raw_data_summary = build_raw_data_summary(indicators)

    return FactorEvidence(
        factor_name="capital",
        trend_signal=scored["trend_signal"],
        score=scored["score"],
        key_findings=scored["key_findings"],
        risk_flags=scored["risk_flags"],
        raw_data_summary=f"{stock_name}（{stock_code}）资金因子：{raw_data_summary}",
    )

def analyze_capital_factor(
    stock_name: str,
    stock_code: str,
    use_rank: bool = True,
    use_margin: bool = True,
) -> tuple[dict[str, Any], FactorEvidence]:
    """
    独立执行资金因子分析。
    返回：
    - indicators
    - 不经过 LLM 的 FactorEvidence
    """
    try:
        flow_df = fetch_capital_flow(stock_code)

        rank_df = fetch_fund_flow_rank(stock_code, indicator="5日") if use_rank else pd.DataFrame()
        margin_df = fetch_margin_data(stock_code) if use_margin else pd.DataFrame()

        indicators = calculate_capital_indicators(
            flow_df=flow_df,
            margin_df=margin_df,
            rank_df=rank_df,
        )

        evidence = build_capital_evidence(
            stock_name=stock_name,
            stock_code=stock_code,
            indicators=indicators,
        )
        return indicators, evidence

    except Exception as e:
        indicators = {
            "data_available": False,
            "data_quality": "failed",
            "warnings": [f"AkShare 数据获取或资金指标计算失败: {str(e)}"],
        }
        evidence = build_capital_evidence(
            stock_name=stock_name,
            stock_code=stock_code,
            indicators=indicators,
        )
        return indicators, evidence