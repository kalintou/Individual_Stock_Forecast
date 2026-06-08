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
    获取个股资金流数据。
    主数据源：ak.stock_individual_fund_flow(stock=..., market=...)
    """
    if ak is None:
        raise RuntimeError("akshare is not installed. Please run: pip install akshare")

    code = str(stock_code).strip()[-6:]
    market = resolve_market(code)

    df = ak.stock_individual_fund_flow(stock=code, market=market)

    if df is None or df.empty:
        raise ValueError(f"No capital flow data returned for {stock_code}")

    date_col = _find_col(df, ["日期", "date"])
    if date_col:
        df = df.copy()
        df[date_col] = pd.to_datetime(df[date_col], errors="coerce")
        df = df.dropna(subset=[date_col]).sort_values(date_col)

    return df.tail(days).reset_index(drop=True)


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
    """
    根据资金流数据计算资金因子指标。
    """
    indicators: dict[str, Any] = {
        "data_available": False,
        "data_quality": "empty",
        "latest_trade_date": None,

        "latest_main_net_inflow": 0.0,
        "main_net_inflow_3d_sum": 0.0,
        "main_net_inflow_5d_sum": 0.0,
        "main_net_inflow_5d_mean": 0.0,
        "main_net_inflow_ratio_5d_mean": 0.0,

        "latest_super_large_net_inflow": 0.0,
        "latest_large_net_inflow": 0.0,
        "latest_medium_net_inflow": 0.0,
        "latest_small_net_inflow": 0.0,

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

        "raw_rows": 0,
        "warnings": [],
    }

    if flow_df is None or flow_df.empty:
        indicators["warnings"].append("个股资金流数据为空")
        return indicators

    df = flow_df.copy()
    indicators["data_available"] = True
    indicators["raw_rows"] = len(df)

    date_col = _find_col(df, ["日期", "date"])
    main_amt_col = _find_col(df, [
        "主力净流入-净额",
        "主力净流入净额",
        "主力净流入",
        "主力净额",
    ])
    main_ratio_col = _find_col(df, [
        "主力净流入-净占比",
        "主力净流入净占比",
        "主力净占比",
    ])
    super_amt_col = _find_col(df, [
        "超大单净流入-净额",
        "超大单净流入净额",
        "超大单净流入",
    ])
    large_amt_col = _find_col(df, [
        "大单净流入-净额",
        "大单净流入净额",
        "大单净流入",
    ])
    medium_amt_col = _find_col(df, [
        "中单净流入-净额",
        "中单净流入净额",
        "中单净流入",
    ])
    small_amt_col = _find_col(df, [
        "小单净流入-净额",
        "小单净流入净额",
        "小单净流入",
    ])
    pct_col = _find_col(df, ["涨跌幅", "涨跌幅%", "pct_chg", "涨跌幅度"])

    if main_amt_col is None:
        indicators["data_quality"] = "missing_main_flow_column"
        indicators["warnings"].append("缺少主力净流入金额字段")
        return indicators

    if date_col:
        df[date_col] = pd.to_datetime(df[date_col], errors="coerce")
        df = df.dropna(subset=[date_col]).sort_values(date_col)

    main_values = [_safe_float(x) for x in df[main_amt_col].tolist()]
    main_ratio_values = (
        [_safe_float(x) for x in df[main_ratio_col].tolist()]
        if main_ratio_col else []
    )

    latest = df.iloc[-1]
    last3 = main_values[-3:]
    last5 = main_values[-5:]

    indicators["data_quality"] = "ok"

    if date_col:
        latest_date = latest[date_col]
        indicators["latest_trade_date"] = str(latest_date.date()) if hasattr(latest_date, "date") else str(latest_date)

    indicators["latest_main_net_inflow"] = _safe_float(latest[main_amt_col])
    indicators["main_net_inflow_3d_sum"] = float(sum(last3))
    indicators["main_net_inflow_5d_sum"] = float(sum(last5))
    indicators["main_net_inflow_5d_mean"] = float(sum(last5) / len(last5)) if last5 else 0.0

    if main_ratio_values:
        last5_ratio = main_ratio_values[-5:]
        indicators["main_net_inflow_ratio_5d_mean"] = (
            float(sum(last5_ratio) / len(last5_ratio)) if last5_ratio else 0.0
        )

    if super_amt_col:
        indicators["latest_super_large_net_inflow"] = _safe_float(latest[super_amt_col])
    if large_amt_col:
        indicators["latest_large_net_inflow"] = _safe_float(latest[large_amt_col])
    if medium_amt_col:
        indicators["latest_medium_net_inflow"] = _safe_float(latest[medium_amt_col])
    if small_amt_col:
        indicators["latest_small_net_inflow"] = _safe_float(latest[small_amt_col])

    indicators["consecutive_inflow_days"] = _last_consecutive_count(main_values, positive=True)
    indicators["consecutive_outflow_days"] = _last_consecutive_count(main_values, positive=False)

    latest_main = indicators["latest_main_net_inflow"]
    latest_small = indicators["latest_small_net_inflow"]

    indicators["main_small_divergence"] = latest_main * latest_small < 0
    indicators["accumulation_signal"] = latest_main > 0 and latest_small < 0
    indicators["retail_chasing_risk"] = latest_main < 0 and latest_small > 0

    # 异常资金流：最近 5 日中，最新值显著偏离均值
    if len(last5) >= 5:
        mean5 = sum(last5) / len(last5)
        std5 = pd.Series(last5).std()
        if std5 and not math.isnan(std5):
            indicators["abnormal_large_inflow"] = latest_main > mean5 + 1.5 * std5 and latest_main > 0
            indicators["abnormal_large_outflow"] = latest_main < mean5 - 1.5 * std5 and latest_main < 0

    if pct_col:
        latest_pct = _safe_float(latest[pct_col])
        indicators["latest_pct_change"] = latest_pct
        # 股价上涨但主力流出，视为价格和资金背离
        indicators["price_fund_divergence"] = latest_pct > 1.0 and latest_main < 0

    # 个股资金流排名，可选
    if rank_df is not None and not rank_df.empty:
        indicators["rank_available"] = True
        rank_row = rank_df.iloc[0].to_dict()
        indicators["fund_flow_rank_summary"] = {
            str(k): str(v)
            for k, v in rank_row.items()
            if k is not None
        }

    # 融资融券，可选
    if margin_df is not None and not margin_df.empty:
        margin = margin_df.copy()

        margin_balance_col = _find_col(margin, ["融资余额", "融资余额(元)", "融资余额（元）"])
        margin_buy_col = _find_col(margin, ["融资买入额", "融资买入额(元)", "融资买入额（元）"])

        if margin_balance_col:
            indicators["margin_available"] = True
            margin_balance_values = [_safe_float(x) for x in margin[margin_balance_col].tolist()]
            latest_balance = margin_balance_values[-1]
            indicators["margin_balance_latest"] = latest_balance

            if len(margin_balance_values) >= 2:
                prev_balance = margin_balance_values[-2]
                if abs(prev_balance) > 1e-9:
                    indicators["margin_balance_change_rate"] = (
                        (latest_balance - prev_balance) / abs(prev_balance) * 100
                    )

        if margin_buy_col:
            latest_buy = _safe_float(margin.iloc[-1][margin_buy_col])
            indicators["margin_buy_latest"] = latest_buy

            latest_balance = indicators.get("margin_balance_latest")
            if latest_balance and abs(latest_balance) > 1e-9:
                indicators["margin_buy_active_ratio"] = latest_buy / abs(latest_balance) * 100

    return indicators


# =========================
# 规则评分
# =========================

def score_capital_factor(indicators: dict[str, Any]) -> dict[str, Any]:
    """
    根据资金指标生成 score、trend_signal、key_findings、risk_flags。
    """
    score = 50
    key_findings: list[str] = []
    risk_flags: list[str] = []

    if not indicators.get("data_available"):
        return {
            "score": 50,
            "trend_signal": "Neutral",
            "key_findings": ["资金流数据不可用，资金因子暂按中性处理。"],
            "risk_flags": ["资金流数据缺失或 AkShare 接口失败，资金面分析置信度下降。"],
        }

    latest_main = _safe_float(indicators.get("latest_main_net_inflow"))
    sum3 = _safe_float(indicators.get("main_net_inflow_3d_sum"))
    sum5 = _safe_float(indicators.get("main_net_inflow_5d_sum"))
    ratio5 = _safe_float(indicators.get("main_net_inflow_ratio_5d_mean"))
    inflow_days = int(indicators.get("consecutive_inflow_days") or 0)
    outflow_days = int(indicators.get("consecutive_outflow_days") or 0)
    super_flow = _safe_float(indicators.get("latest_super_large_net_inflow"))
    large_flow = _safe_float(indicators.get("latest_large_net_inflow"))
    medium_flow = _safe_float(indicators.get("latest_medium_net_inflow"))
    small_flow = _safe_float(indicators.get("latest_small_net_inflow"))

    # 1. 最新主力净流入方向
    if latest_main > 0:
        score += 8
        key_findings.append(f"最近一个交易日主力资金净流入 {_format_money_cn(latest_main)}。")
    elif latest_main < 0:
        score -= 8
        key_findings.append(f"最近一个交易日主力资金净流出 {_format_money_cn(abs(latest_main))}。")

    # 2. 3日、5日资金持续性
    if sum3 > 0:
        score += 5
        key_findings.append(f"近3日主力资金合计净流入 {_format_money_cn(sum3)}。")
    elif sum3 < 0:
        score -= 5
        key_findings.append(f"近3日主力资金合计净流出 {_format_money_cn(abs(sum3))}。")

    if sum5 > 0:
        score += 6
        key_findings.append(f"近5日主力资金合计净流入 {_format_money_cn(sum5)}。")
    elif sum5 < 0:
        score -= 6
        key_findings.append(f"近5日主力资金合计净流出 {_format_money_cn(abs(sum5))}。")

    # 3. 主力净流入占比
    if ratio5 >= 5:
        score += 12
        key_findings.append(f"近5日主力净流入占比均值约为 {ratio5:.2f}%，资金流入强度较高。")
    elif ratio5 >= 2:
        score += 6
        key_findings.append(f"近5日主力净流入占比均值约为 {ratio5:.2f}%，资金面略偏积极。")
    elif ratio5 <= -5:
        score -= 12
        risk_flags.append(f"近5日主力净流入占比均值约为 {ratio5:.2f}%，主力撤离迹象较明显。")
    elif ratio5 <= -2:
        score -= 6
        risk_flags.append(f"近5日主力净流入占比均值约为 {ratio5:.2f}%，资金面偏弱。")

    # 4. 连续净流入/流出
    if inflow_days >= 3:
        score += 10
        key_findings.append(f"主力资金已连续 {inflow_days} 个交易日净流入，资金持续性较好。")
    elif inflow_days == 2:
        score += 5
        key_findings.append("主力资金连续 2 个交易日净流入，短期资金面有所改善。")

    if outflow_days >= 3:
        score -= 12
        risk_flags.append(f"主力资金已连续 {outflow_days} 个交易日净流出，存在资金持续撤离风险。")
    elif outflow_days == 2:
        score -= 6
        risk_flags.append("主力资金连续 2 个交易日净流出，短期资金面偏弱。")

    # 5. 主力与小单背离
    if indicators.get("accumulation_signal"):
        score += 10
        key_findings.append("出现“主力净流入、小单净流出”的结构，可能存在主力吸筹迹象。")

    if indicators.get("retail_chasing_risk"):
        score -= 12
        risk_flags.append("出现“主力净流出、小单净流入”的结构，存在散户接盘风险。")

    # 资金层级结构：超大单 / 大单 / 中单 / 小单
    if super_flow < 0 and large_flow < 0:
        risk_flags.append(
            f"超大单和大单均为净流出，其中超大单净流出 {_format_money_cn(abs(super_flow))}，"
            f"大单净流出 {_format_money_cn(abs(large_flow))}，显示大资金方向偏弱。"
        )

    if super_flow > 0 and large_flow > 0:
        key_findings.append(
            f"超大单和大单均为净流入，其中超大单净流入 {_format_money_cn(super_flow)}，"
            f"大单净流入 {_format_money_cn(large_flow)}，显示大资金参与度较高。"
        )

    if medium_flow > 0 and super_flow < 0 and large_flow < 0:
        key_findings.append(
            "中单资金净流入，但超大单和大单净流出，显示不同资金层级之间存在分歧。"
        )

    if small_flow > 0 and latest_main < 0:
        risk_flags.append(
            "小单资金净流入但主力资金净流出，需警惕散户承接主力抛压的风险。"
        )

    # 6. 异常资金流
    if indicators.get("abnormal_large_inflow"):
        score += 8
        key_findings.append("最新主力净流入显著高于近5日波动水平，存在异常流入迹象。")

    if indicators.get("abnormal_large_outflow"):
        score -= 10
        risk_flags.append("最新主力净流出显著高于近5日波动水平，存在异常流出风险。")

    # 8. 资金流排名增强判断
    if indicators.get("price_fund_divergence"):
        score -= 6
        risk_flags.append("股价上涨但主力资金净流出，存在价格与资金背离。")

    rank_summary = indicators.get("fund_flow_rank_summary")

    if isinstance(rank_summary, dict):
        rank_5d_amt = _safe_float(rank_summary.get("5日主力净流入-净额"))
        rank_5d_ratio = _safe_float(rank_summary.get("5日主力净流入-净占比"))

        if rank_5d_amt < 0 and rank_5d_ratio <= -5:
            risk_flags.append(
                f"资金流排名数据也显示近5日主力净流出占比较高，约为 {rank_5d_ratio:.2f}%。"
            )
            score -= 3

        elif rank_5d_amt > 0 and rank_5d_ratio >= 5:
            key_findings.append(
                f"资金流排名数据也显示近5日主力净流入占比较高，约为 {rank_5d_ratio:.2f}%。"
            )
            score += 3

    # 9. 融资融券增强判断
    if indicators.get("margin_available"):
        margin_change = indicators.get("margin_balance_change_rate")
        margin_active = indicators.get("margin_buy_active_ratio")

        if margin_change is not None:
            margin_change = _safe_float(margin_change)
            if margin_change > 3 and latest_main > 0:
                score += 5
                key_findings.append(f"融资余额环比上升约 {margin_change:.2f}%，且主力资金净流入，杠杆资金情绪偏积极。")
            elif margin_change > 5 and latest_main < 0:
                score -= 5
                risk_flags.append(f"融资余额环比上升约 {margin_change:.2f}%，但主力资金净流出，可能存在杠杆资金追高风险。")
            elif margin_change < -3:
                score -= 3
                risk_flags.append(f"融资余额环比下降约 {abs(margin_change):.2f}%，杠杆资金参与度下降。")
            else:
                key_findings.append(
                    f"融资余额环比变化约为 {margin_change:.2f}%，变化幅度不大，杠杆资金信号偏中性。"
                )

        if margin_active is not None:
            margin_active = _safe_float(margin_active)
            if margin_active > 5:
                key_findings.append(f"融资买入额/融资余额约为 {margin_active:.2f}%，融资买入活跃度较高。")
    else:
        risk_flags.append("融资融券数据不可用，本次资金因子未纳入杠杆资金判断。")

    # 9. 数据质量
    warnings = indicators.get("warnings") or []
    if warnings:
        risk_flags.extend([str(w) for w in warnings])
        score -= 3

    # 低分保护：
    # 如果只是主力资金持续流出，但没有出现散户接盘、异常大额流出、
    # 股价资金背离、融资追高等复合风险，则不轻易打到个位数。
    severe_compound_risk = (
        indicators.get("retail_chasing_risk")
        or indicators.get("abnormal_large_outflow")
        or indicators.get("price_fund_divergence")
    )

    margin_change_for_floor = indicators.get("margin_balance_change_rate")
    if margin_change_for_floor is not None:
        margin_change_for_floor = _safe_float(margin_change_for_floor)
        if margin_change_for_floor > 5 and latest_main < 0:
            severe_compound_risk = True

    score = int(round(score))

    if score < 20 and not severe_compound_risk:
        score = 20

    score = max(0, min(100, score))

    if score >= 60:
        trend_signal = "Bullish"
    elif score >= 40:
        trend_signal = "Neutral"
    else:
        trend_signal = "Bearish"

    if not key_findings:
        key_findings.append("资金流入流出信号混杂，资金面暂未形成明确方向。")

    # 去重并限制长度
    key_findings = list(dict.fromkeys(key_findings))[:6]
    risk_flags = list(dict.fromkeys(risk_flags))[:6]

    return {
        "score": score,
        "trend_signal": trend_signal,
        "key_findings": key_findings,
        "risk_flags": risk_flags,
    }


# =========================
# Prompt 数据与 Evidence 构建
# =========================

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
    """
    生成 raw_data_summary，保证即使没有 LLM 也能输出。
    """
    if not indicators.get("data_available"):
        return "个股资金流数据不可用，资金因子暂按中性处理。"

    parts = []

    date = indicators.get("latest_trade_date")
    if date:
        parts.append(f"最新资金流交易日为 {date}")

    parts.append(
        f"最近一日{_format_flow_direction(indicators.get('latest_main_net_inflow', 0))}"
    )
    parts.append(
        f"近3日{_format_flow_direction(indicators.get('main_net_inflow_3d_sum', 0))}"
    )
    parts.append(
        f"近5日{_format_flow_direction(indicators.get('main_net_inflow_5d_sum', 0))}"
    )
    parts.append(
        f"近5日主力净流入占比均值约为 {_safe_float(indicators.get('main_net_inflow_ratio_5d_mean')):.2f}%"
    )

    super_flow = _safe_float(indicators.get("latest_super_large_net_inflow"))
    large_flow = _safe_float(indicators.get("latest_large_net_inflow"))
    medium_flow = _safe_float(indicators.get("latest_medium_net_inflow"))
    small_flow = _safe_float(indicators.get("latest_small_net_inflow"))

    if super_flow != 0 or large_flow != 0:
        parts.append(
            f"最近一日{_format_flow_direction(super_flow, '超大单资金')}，"
            f"{_format_flow_direction(large_flow, '大单资金')}"
        )

    if medium_flow != 0 or small_flow != 0:
        parts.append(
            f"最近一日{_format_flow_direction(medium_flow, '中单资金')}，"
            f"{_format_flow_direction(small_flow, '小单资金')}"
        )

    if indicators.get("rank_available"):
        rank_summary = indicators.get("fund_flow_rank_summary")
        if isinstance(rank_summary, dict):
            rank_5d_ratio = rank_summary.get("5日主力净流入-净占比")
            rank_5d_amt = rank_summary.get("5日主力净流入-净额")

            if rank_5d_ratio is not None and rank_5d_amt is not None:
                parts.append(
                    f"资金流排名数据中，近5日主力净流入为 "
                    f"{_format_flow_direction(_safe_float(rank_5d_amt), '主力资金')}，"
                    f"净占比约为 {_safe_float(rank_5d_ratio):.2f}%"
                )

    if indicators.get("margin_available"):
        change = indicators.get("margin_balance_change_rate")
        active_ratio = indicators.get("margin_buy_active_ratio")

        if change is not None:
            change_value = _safe_float(change)

            if abs(change_value) < 3:
                parts.append(
                    f"融资余额环比变化约为 {change_value:.2f}%，变化幅度不大，杠杆资金信号偏中性"
                )
            elif change_value > 0:
                parts.append(
                    f"融资余额环比上升约为 {change_value:.2f}%，杠杆资金参与度有所提高"
                )
            else:
                parts.append(
                    f"融资余额环比下降约为 {abs(change_value):.2f}%，杠杆资金参与度有所下降"
                )

        if active_ratio is not None:
            parts.append(
                f"融资买入额/融资余额约为 {_safe_float(active_ratio):.2f}%"
            )

    else:
        parts.append("融资融券数据不可用或未覆盖该股票")

    return "；".join(parts) + "。"


def build_capital_evidence(
    stock_name: str,
    stock_code: str,
    indicators: dict[str, Any],
    llm_result: Optional[dict[str, Any]] = None,
) -> FactorEvidence:
    """
    生成 FactorEvidence。

    注意：
    - score 和 trend_signal 以规则评分为准。
    - LLM 只允许补充 key_findings、risk_flags、raw_data_summary 的表达。
    """
    scored = score_capital_factor(indicators)

    key_findings = scored["key_findings"]
    risk_flags = scored["risk_flags"]
    raw_data_summary = build_raw_data_summary(indicators)

    if isinstance(llm_result, dict):
        llm_findings = llm_result.get("key_findings")
        llm_risks = llm_result.get("risk_flags")
        llm_summary = llm_result.get("raw_data_summary")

        if isinstance(llm_findings, list) and llm_findings:
            key_findings = [str(x) for x in llm_findings][:5]

        if isinstance(llm_risks, list):
            merged_risks = risk_flags + [str(x) for x in llm_risks]
            risk_flags = list(dict.fromkeys(merged_risks))[:5]

        if isinstance(llm_summary, str) and llm_summary.strip():
            raw_data_summary = llm_summary.strip()

    return FactorEvidence(
        factor_name="capital",
        trend_signal=scored["trend_signal"],
        score=scored["score"],
        key_findings=key_findings,
        risk_flags=risk_flags,
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