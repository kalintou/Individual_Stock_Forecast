"""
LangGraph node functions for the stock forecast agent workflow.

Phase 1: intent_clarification → market_structure → final_answer
Phase 2: + sector_router → 4 factor nodes → cross_sector_fusion → final_answer
"""

import json
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from core.state import AgentState
from core.constants import AgentStatus
from core.schemas import (
    EvidenceItem,
    UserIntent,
    MarketStructure,
    SectorRoute,
    FactorEvidence,
    CompositeAssessment,
    FinalAnswer,
)
from core.logging import log_node_start, log_node_end, log_info, log_error
from planner.base import BasePlanner

from capital_factor import (
    fetch_capital_flow,
    fetch_fund_flow_rank,
    fetch_margin_data,
    calculate_capital_indicators,
    build_capital_prompt_data,
    build_capital_evidence,
)

try:
    from core.schemas import EvidenceLogItem
except Exception:
    EvidenceLogItem = None

# =============================================================================
# Stock Data Helpers (internal, akshare-based)
# =============================================================================

_STOCK_NAME_CACHE: dict[str, str] | None = None


def _load_stock_name_cache() -> dict[str, str]:
    """Load or build a name -> code mapping cache."""
    global _STOCK_NAME_CACHE
    if _STOCK_NAME_CACHE is not None:
        return _STOCK_NAME_CACHE
    try:
        import akshare as ak

        df = ak.stock_info_a_code_name()
        mapping = {}
        for _, row in df.iterrows():
            code = str(row["code"]).strip()
            name = str(row["name"]).strip()
            mapping[name] = code
            clean_name = name.replace("*ST", "").replace("ST", "").strip()
            if clean_name and clean_name != name:
                mapping[clean_name] = code
        _STOCK_NAME_CACHE = mapping
        return mapping
    except Exception as e:
        log_error("stock_cache", RuntimeError(f"Failed to load stock cache: {e}"))
        return {}


def _resolve_stock_code(stock_name: str) -> str:
    """Resolve stock name to 6-digit code."""
    if stock_name.isdigit() and len(stock_name) == 6:
        return stock_name
    cache = _load_stock_name_cache()
    if stock_name in cache:
        return cache[stock_name]
    for name, code in cache.items():
        if stock_name in name or name in stock_name:
            return code
    return ""


def _fetch_stock_basic(stock_code: str) -> dict:
    """Fetch basic stock info. Tries multiple CDN nodes to bypass server blocks."""
    import time
    from curl_cffi import requests as cr

    market_code = 1 if str(stock_code).startswith("6") else 0
    params = {
        "fltt": "2",
        "invt": "2",
        "fields": "f57,f58,f84,f85,f127,f116,f117,f189,f43",
        "secid": f"{market_code}.{stock_code}",
    }

    # 东方财富主域名 push2 常被限制，轮询多个 CDN 子域名
    domains = [
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
            url = f"https://{domain}/api/qt/stock/get"
            r = cr.get(url, params=params, timeout=10, impersonate="chrome120")
            if r.status_code == 200:
                data = r.json()
                d = data.get("data", {})
                if d:
                    return {
                        "股票代码": d.get("f57", stock_code),
                        "股票简称": d.get("f58", stock_code),
                        "总股本": d.get("f84"),
                        "流通股": d.get("f85"),
                        "行业": d.get("f127", "未知"),
                        "总市值": d.get("f116"),
                        "流通市值": d.get("f117"),
                        "上市时间": d.get("f189"),
                        "最新价": d.get("f43"),
                    }
        except Exception:
            pass
        time.sleep(0.2)

    # 保底 fallback
    return {"股票代码": stock_code, "股票简称": stock_code}


def _fetch_recent_kline(stock_code: str, days: int = 10) -> list[dict]:
    """Fetch recent daily K-line data via curl_cffi with fallback nodes."""
    import time
    from curl_cffi import requests as cr

    market_code = 1 if str(stock_code).startswith("6") else 0
    params = {
        "secid": f"{market_code}.{stock_code}",
        "fields1": "f1,f2,f3,f4,f5,f6",
        "fields2": "f51,f52,f53,f54,f55,f56,f57,f58,f59,f60,f61",
        "klt": "101",
        "fqt": "0",
        "end": "20500101",
        "lmt": str(days + 30),
    }

    # push2his 多节点轮询
    domains = [
        "push2his.eastmoney.com",
        "1.push2his.eastmoney.com",
        "11.push2his.eastmoney.com",
        "22.push2his.eastmoney.com",
    ]

    for domain in domains:
        try:
            url = f"https://{domain}/api/qt/stock/kline/get"
            r = cr.get(url, params=params, timeout=15, impersonate="chrome120")
            if r.status_code == 200:
                data = r.json()
                klines = data.get("data", {}).get("klines", [])
                if not klines:
                    continue
                # Parse kline strings: date,open,close,high,low,volume,amount,amplitude,pct_change,change_amount,turnover
                records = []
                for line in klines[-days:]:
                    parts = line.split(",")
                    if len(parts) >= 6:
                        records.append({
                            "日期": parts[0],
                            "收盘": float(parts[2]) if parts[2] else None,
                            "涨跌幅": float(parts[8]) if len(parts) > 8 and parts[8] else None,
                            "成交量": float(parts[5]) if parts[5] else None,
                        })
                return records
        except Exception:
            pass
        time.sleep(0.2)

    return []


def _fetch_valuation(stock_code: str) -> dict:
    """Fetch latest valuation metrics (PE, PB, etc.) via curl_cffi with fallback nodes."""
    import time
    from curl_cffi import requests as cr

    market_code = 1 if str(stock_code).startswith("6") else 0
    params = {
        "fltt": "2",
        "invt": "2",
        "fields": "f44,f45,f60,f162,f167,f168",
        "secid": f"{market_code}.{stock_code}",
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
            url = f"https://{domain}/api/qt/stock/get"
            r = cr.get(url, params=params, timeout=10, impersonate="chrome120")
            if r.status_code == 200:
                data = r.json()
                d = data.get("data", {})
                if not d:
                    continue
                high = d.get("f44")
                low = d.get("f45")
                prev = d.get("f60")
                amplitude = None
                if high and low and prev and prev != 0:
                    amplitude = round((high - low) / prev * 100, 2)
                return {
                    "PE_DYNAMIC": d.get("f162", "N/A"),
                    "PB": d.get("f167", "N/A"),
                    "换手率": d.get("f168", "N/A"),
                    "振幅": amplitude if amplitude is not None else "N/A",
                }
        except Exception:
            pass
        time.sleep(0.2)

    return {}


def _to_float(value) -> float | None:
    """Convert common akshare values to float, returning None for missing values."""
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    text = str(value).strip()
    if not text or text in {"-", "--", "N/A", "nan", "None"}:
        return None
    multiplier = 1.0
    if text.endswith("%"):
        text = text[:-1]
        multiplier = 0.01
    text = text.replace(",", "")
    try:
        return float(text) * multiplier
    except ValueError:
        return None


def _safe_div(numerator, denominator) -> float | None:
    """Safely divide two numeric-like values."""
    num = _to_float(numerator)
    den = _to_float(denominator)
    if num is None or den is None or den == 0:
        return None
    return num / den


def _first_available(data: dict, *keys: str):
    """Return the first non-empty value for any of the candidate keys."""
    for key in keys:
        if key in data:
            value = data.get(key)
            if _to_float(value) is not None:
                return value
    return None


def _score_fundamental_metrics(metrics: dict) -> int:
    """Create a conservative transparent score hint from computed metrics."""
    score = 50

    roe = metrics.get("roe")
    if roe is not None:
        score += 10 if roe >= 0.15 else 5 if roe >= 0.08 else -5

    gross_margin = metrics.get("gross_margin")
    if gross_margin is not None:
        score += 5 if gross_margin >= 0.30 else -3 if gross_margin < 0.10 else 0

    net_margin = metrics.get("net_margin")
    if net_margin is not None:
        score += 5 if net_margin >= 0.10 else -3 if net_margin < 0.03 else 0

    revenue_yoy = metrics.get("revenue_yoy")
    if revenue_yoy is not None:
        score += 6 if revenue_yoy >= 0.10 else -6 if revenue_yoy < -0.05 else 0

    net_profit_yoy = metrics.get("net_profit_yoy")
    if net_profit_yoy is not None:
        score += 6 if net_profit_yoy >= 0.10 else -8 if net_profit_yoy < -0.10 else 0

    pe = metrics.get("pe")
    if pe is not None:
        score += 5 if 0 < pe <= 30 else -6 if pe > 60 or pe <= 0 else 0

    pb = metrics.get("pb")
    if pb is not None:
        score += 3 if 0 < pb <= 5 else -4 if pb > 10 or pb <= 0 else 0

    debt_to_asset = metrics.get("debt_to_asset")
    if debt_to_asset is not None:
        score += 5 if debt_to_asset <= 0.50 else -8 if debt_to_asset >= 0.75 else 0

    ocf_to_net_profit = metrics.get("ocf_to_net_profit")
    if ocf_to_net_profit is not None:
        score += 5 if ocf_to_net_profit >= 1 else -6 if ocf_to_net_profit < 0.5 else 0

    missing_count = len(metrics.get("missing_fields", []))
    score -= min(missing_count * 2, 12)
    return max(0, min(100, int(round(score))))


def _calculate_fundamental_metrics(reports: dict, valuation: dict, basic: dict) -> dict:
    """Calculate course-display fundamental metrics from statements and fallbacks."""
    current = reports.get("current", {}) or {}
    previous = reports.get("previous", {}) or {}

    revenue = _first_available(current, "营业收入", "营业总收入")
    operating_cost = _first_available(current, "营业成本", "营业总成本")
    net_profit = _first_available(current, "净利润")
    parent_net_profit = _first_available(current, "归母净利润", "归属于母公司所有者的净利润")
    total_assets = _first_available(current, "总资产", "资产总计")
    total_liabilities = _first_available(current, "总负债", "负债合计")
    parent_equity = _first_available(current, "归母净资产", "归属于母公司股东权益合计", "所有者权益合计")
    operating_cash_flow = _first_available(current, "经营现金流净额", "经营活动产生的现金流量净额")

    previous_revenue = _first_available(previous, "营业收入", "营业总收入")
    previous_net_profit = _first_available(previous, "净利润")
    previous_parent_equity = _first_available(previous, "归母净资产", "归属于母公司股东权益合计", "所有者权益合计")

    total_market_value = _to_float(valuation.get("总市值"))
    parent_net_profit_float = _to_float(parent_net_profit)
    parent_equity_float = _to_float(parent_equity)
    previous_parent_equity_float = _to_float(previous_parent_equity)

    average_parent_equity = None
    if parent_equity_float is not None and previous_parent_equity_float is not None:
        average_parent_equity = (parent_equity_float + previous_parent_equity_float) / 2

    pe = _safe_div(total_market_value, parent_net_profit_float)
    if pe is None:
        pe = _to_float(valuation.get("PE_DYNAMIC"))

    pb = _safe_div(total_market_value, parent_equity_float)
    if pb is None:
        pb = _to_float(valuation.get("PB"))

    gross_margin = None
    if _to_float(revenue) is not None and _to_float(operating_cost) is not None:
        gross_margin = _safe_div(_to_float(revenue) - _to_float(operating_cost), revenue)

    metrics = {
        "industry": basic.get("行业", "未知"),
        "pe": pe,
        "pb": pb,
        "roe": _safe_div(parent_net_profit_float, average_parent_equity),
        "gross_margin": gross_margin,
        "net_margin": _safe_div(net_profit, revenue),
        "revenue_yoy": _safe_div(_to_float(revenue) - _to_float(previous_revenue), previous_revenue)
        if _to_float(revenue) is not None and _to_float(previous_revenue) is not None
        else None,
        "net_profit_yoy": _safe_div(_to_float(net_profit) - _to_float(previous_net_profit), previous_net_profit)
        if _to_float(net_profit) is not None and _to_float(previous_net_profit) is not None
        else None,
        "debt_to_asset": _safe_div(total_liabilities, total_assets),
        "ocf_to_net_profit": _safe_div(operating_cash_flow, net_profit),
        "data_sources": reports.get("data_sources", ["利润表", "资产负债表", "现金流量表", "行情数据"]),
    }

    labels = {
        "pe": "PE",
        "pb": "PB",
        "roe": "ROE",
        "gross_margin": "毛利率",
        "net_margin": "净利率",
        "revenue_yoy": "营收同比",
        "net_profit_yoy": "净利润同比",
        "debt_to_asset": "资产负债率",
        "ocf_to_net_profit": "经营现金流/净利润",
    }
    metrics["missing_fields"] = [label for key, label in labels.items() if metrics.get(key) is None]
    metrics["score_hint"] = _score_fundamental_metrics(metrics)
    return metrics


def _format_ratio(value) -> str:
    if value is None:
        return "N/A"
    return f"{value * 100:.2f}%"


def _format_number(value) -> str:
    if value is None:
        return "N/A"
    return f"{value:.2f}"


def _format_fundamental_metrics(metrics: dict) -> str:
    """Format fundamental metrics for the LLM prompt."""
    missing = metrics.get("missing_fields", [])
    sources = metrics.get("data_sources", [])
    return (
        "【估值】\n"
        f"PE: {_format_number(metrics.get('pe'))}\n"
        f"PB: {_format_number(metrics.get('pb'))}\n\n"
        "【盈利能力】\n"
        f"ROE: {_format_ratio(metrics.get('roe'))}\n"
        f"毛利率: {_format_ratio(metrics.get('gross_margin'))}\n"
        f"净利率: {_format_ratio(metrics.get('net_margin'))}\n\n"
        "【成长性】\n"
        f"营收同比: {_format_ratio(metrics.get('revenue_yoy'))}\n"
        f"净利润同比: {_format_ratio(metrics.get('net_profit_yoy'))}\n\n"
        "【财务安全】\n"
        f"资产负债率: {_format_ratio(metrics.get('debt_to_asset'))}\n\n"
        "【现金流质量】\n"
        f"经营现金流/净利润: {_format_number(metrics.get('ocf_to_net_profit'))}\n\n"
        "【数据质量】\n"
        f"缺失字段: {', '.join(missing) if missing else '无'}\n"
        f"数据来源: {', '.join(sources) if sources else '未知'}\n"
        f"Python预评分: {metrics.get('score_hint', 50)}/100"
    )


def _to_em_statement_code(stock_code: str) -> str:
    """6 位 A 股代码 -> 东财三表接口格式（如 SH600519）。"""
    c = (stock_code or "").strip()
    if len(c) != 6 or not c.isdigit():
        return ""
    if c.startswith("6"):
        return f"SH{c}"
    if c.startswith(("0", "3")):
        return f"SZ{c}"
    if c.startswith(("8", "4")):
        return f"BJ{c}"
    return ""


def _extract_statement_rows(df, date_col_candidates: tuple[str, ...]) -> tuple[dict, dict]:
    """从三表 DataFrame 提取最近两期行，返回 (current_row_dict, previous_row_dict)。"""
    if df is None or df.empty:
        return {}, {}
    sort_col = next((c for c in date_col_candidates if c in df.columns), None)
    if sort_col:
        df = df.sort_values(sort_col, ascending=False, ignore_index=True)
    current = dict(df.iloc[0]) if len(df) >= 1 else {}
    previous = dict(df.iloc[1]) if len(df) >= 2 else {}
    return current, previous


def _pick(row: dict, *keys: str):
    """从 row 中按候选键顺序取第一个非空值。"""
    for k in keys:
        v = row.get(k)
        if v is not None and v == v:  # not NaN
            try:
                if str(v).strip():
                    return v
            except Exception:
                return v
    return None


def _row_to_metric_dict(row) -> dict:
    """Convert a dataframe row to a normalized dict with only useful scalar values."""
    if row is None:
        return {}
    result = {}
    for key, value in row.items():
        if key in {"股票代码", "股票简称", "报告期", "公告日期", "报告类型"}:
            continue
        result[str(key)] = value
    return result


def _fetch_financial_reports(stock_code: str) -> dict:
    """
    Fetch recent financial statement data from akshare.

    使用东方财富资产负债表、利润表、现金流量表获取绝对值指标；
    辅以新浪财经财务指标补充比率数据。
    """
    reports: dict = {
        "current": {},
        "previous": {},
        "data_sources": ["行情数据"],
    }
    sources: list[str] = []

    try:
        import akshare as ak
    except ImportError:
        return reports

    stmt_code = _to_em_statement_code(stock_code)
    date_cols = ("REPORT_DATE", "REPORTDATE", "报告期")

    # 1) 资产负债表 -> 总资产、总负债、归母净资产
    if stmt_code:
        try:
            df = ak.stock_balance_sheet_by_report_em(symbol=stmt_code)
            cur, prev = _extract_statement_rows(df, date_cols)
            if cur:
                def _merge_balance(dest: dict, row: dict) -> None:
                    v = _pick(row, "TOTAL_ASSETS", "TOTALASSETS")
                    if v is not None:
                        dest["总资产"] = v
                    v = _pick(row, "TOTAL_LIABILITIES", "TOTALLIABILITIES", "TOTAL_LIAB")
                    if v is not None:
                        dest["总负债"] = v
                    v = _pick(row, "TOTAL_PARENT_EQUITY", "PARENT_EQUITY", "HOLDER_EQUITY")
                    if v is not None:
                        dest["归母净资产"] = v

                _merge_balance(reports["current"], cur)
                _merge_balance(reports["previous"], prev)
                sources.append("资产负债表")
        except Exception as e:
            log_error("fundamental_balance_em", RuntimeError(f"Balance sheet: {e}"))

    # 2) 利润表 -> 营业收入、营业成本、净利润、归母净利润
    if stmt_code:
        try:
            df = ak.stock_profit_sheet_by_report_em(symbol=stmt_code)
            cur, prev = _extract_statement_rows(df, date_cols)
            if cur:
                def _merge_profit(dest: dict, row: dict) -> None:
                    v = _pick(row, "TOTAL_OPERATE_INCOME", "OPERATE_INCOME", "OPERATING_INCOME")
                    if v is not None:
                        dest["营业收入"] = v
                    v = _pick(row, "OPERATE_COST", "TOTAL_OPERATE_COST")
                    if v is not None:
                        dest["营业成本"] = v
                    v = _pick(row, "NETPROFIT", "NET_PROFIT")
                    if v is not None:
                        dest["净利润"] = v
                    v = _pick(row, "PARENT_NETPROFIT", "HOLDER_NETPROFIT")
                    if v is not None:
                        dest["归母净利润"] = v

                _merge_profit(reports["current"], cur)
                _merge_profit(reports["previous"], prev)
                sources.append("利润表")
        except Exception as e:
            log_error("fundamental_profit_em", RuntimeError(f"Profit sheet: {e}"))

    # 3) 现金流量表 -> 经营现金流净额
    if stmt_code:
        try:
            df = ak.stock_cash_flow_sheet_by_report_em(symbol=stmt_code)
            cur, prev = _extract_statement_rows(df, date_cols)
            if cur:
                def _merge_cashflow(dest: dict, row: dict) -> None:
                    v = _pick(row, "NETCASH_OPERATE", "NETCASH_FLOWS_OPERATING", "OPERATE_NET_CASH_FLOW")
                    if v is not None:
                        dest["经营现金流净额"] = v

                _merge_cashflow(reports["current"], cur)
                _merge_cashflow(reports["previous"], prev)
                sources.append("现金流量表")
        except Exception as e:
            log_error("fundamental_cashflow_em", RuntimeError(f"Cash flow sheet: {e}"))

    # 4) 新浪财经：财务指标（比率等），用 setdefault 补缺
    try:
        indicator_df = ak.stock_financial_analysis_indicator(symbol=stock_code)
        if indicator_df is not None and not indicator_df.empty:
            recent = indicator_df.head(2)
            if len(recent) >= 1:
                for k, v in _row_to_metric_dict(recent.iloc[0]).items():
                    reports["current"].setdefault(k, v)
            if len(recent) >= 2:
                for k, v in _row_to_metric_dict(recent.iloc[1]).items():
                    reports["previous"].setdefault(k, v)
            sources.append("新浪财经财务指标")
    except Exception as e:
        log_error("fundamental_reports_sina", RuntimeError(f"Sina financial indicators: {e}"))

    if sources:
        reports["data_sources"] = sources + ["行情数据"]
    return reports


def _fetch_capital_flow(stock_code: str, days: int = 5) -> list[dict]:
    """Fetch recent capital flow data."""
    try:
        import akshare as ak

        df = ak.stock_individual_fund_flow(stock=stock_code, market="sh")
        if df.empty:
            return []
        recent = df.head(days)
        return recent[
            ["日期", "主力净流入-净额", "主力净流入-净占比", "小单净流入-净额"]
        ].to_dict("records")
    except Exception as e:
        return []


def _fetch_news(stock_code: str, top_n: int = 5) -> list[dict]:
    """Fetch recent news headlines."""
    try:
        import akshare as ak

        df = ak.stock_news_em(symbol=stock_code)
        if df.empty:
            return []
        recent = df.head(top_n)
        return recent[["新闻标题", "发布时间"]].to_dict("records")
    except Exception as e:
        return []


# 全局缓存：程序运行期间只抓取一次热点概念，后续直接读取
_HOT_CONCEPTS_RESULT: list[dict] | None = None


def _fetch_hot_concepts(top_n: int = 10) -> list[dict]:
    """Fetch today's hot concept sectors from Sina Finance.
    Uses Sina's concept board API which is not blocked by Eastmoney restrictions.
    Results are cached globally during the program lifetime.
    """
    global _HOT_CONCEPTS_RESULT
    import json
    import re
    from curl_cffi import requests as cr

    if _HOT_CONCEPTS_RESULT is not None:
        return _HOT_CONCEPTS_RESULT[:top_n]

    try:
        url = "http://money.finance.sina.com.cn/q/view/newFLJK.php"
        params = {"param": "class", "client": "autocallidentifykey="}
        r = cr.get(url, params=params, timeout=15, impersonate="chrome120")
        if r.status_code != 200:
            return []

        # Parse JS variable: var S_Finance_bankuai_class = {"gn_xxx":"gn_xxx,name,count,price,change,...",...};
        text = r.text
        json_start = text.find("{", text.find("var S_Finance_bankuai_class"))
        json_end = text.rfind("};")
        if json_end == -1:
            json_end = text.rfind("}")

        data = json.loads(text[json_start : json_end + 1])

        concepts = []
        for v in data.values():
            parts = v.split(",")
            if len(parts) >= 5:
                try:
                    change = float(parts[4]) if parts[4] else 0.0
                except ValueError:
                    change = 0.0
                concepts.append({
                    "板块名称": parts[1],
                    "涨跌幅": change,
                })

        # Sort by 涨跌幅 descending
        concepts.sort(key=lambda x: x["涨跌幅"], reverse=True)
        _HOT_CONCEPTS_RESULT = concepts
        return concepts[:top_n]
    except Exception:
        return []


def _fetch_longhubang(stock_code: str) -> list[dict]:
    """Fetch 龙虎榜 (Dragon Tiger List) data via curl_cffi directly."""
    from curl_cffi import requests as cr

    try:
        url = "https://datacenter-web.eastmoney.com/api/data/v1/get"
        params = {
            "sortColumns": "SECURITY_CODE,TRADE_DATE",
            "sortTypes": "1,-1",
            "pageSize": "50",
            "pageNumber": "1",
            "reportName": "RPT_DAILYBILLBOARD_DETAILSNEW",
            "columns": "SECURITY_CODE,SECURITY_NAME_ABBR,TRADE_DATE,EXPLAIN,CLOSE_PRICE,CHANGE_RATE",
            "filter": f'(SECURITY_CODE="{stock_code}")',
        }
        r = cr.get(url, params=params, timeout=15, impersonate="chrome120")
        if r.status_code != 200:
            return []

        data = r.json()
        result = data.get("result", {})
        items = result.get("data", []) if result else []
        if not items:
            return []

        records = []
        for item in items[:3]:
            records.append({
                "代码": item.get("SECURITY_CODE", ""),
                "名称": item.get("SECURITY_NAME_ABBR", ""),
                "上榜日期": item.get("TRADE_DATE", ""),
                "上榜原因": item.get("EXPLAIN", ""),
                "收盘价": item.get("CLOSE_PRICE", ""),
                "涨跌幅": item.get("CHANGE_RATE", ""),
            })
        return records
    except Exception:
        return []


def _fetch_stock_hot_rank(stock_code: str) -> dict:
    """Fetch stock popularity ranking via curl_cffi directly."""
    from curl_cffi import requests as cr

    try:
        # Convert stock code to Sina format (e.g., 600519 -> SH600519, 000001 -> SZ000001)
        prefix = "SH" if str(stock_code).startswith("6") else "SZ"
        sec_code = f"{prefix}{stock_code}"

        url = "https://emappdata.eastmoney.com/stockrank/getAllCurrentList"
        payload = {"appId": "appId01", "globalId": "globalId", "pageNo": 1, "pageSize": 100}
        r = cr.post(url, json=payload, timeout=15, impersonate="chrome120")
        if r.status_code != 200:
            return {}

        data = r.json()
        if data.get("status") != 0:
            return {}

        items = data.get("data", [])
        for item in items:
            if item.get("sc") == sec_code:
                return {"人气排名": item.get("rk", "N/A")}

        # Not in top 100
        return {"人气排名": "100+"}
    except Exception:
        return {}


def _fetch_industry_sectors(top_n: int = 10) -> list[dict]:
    """Fetch industry sector performance data from Sina Finance.
    Uses Sina's industry board API which bypasses Eastmoney restrictions.
    """
    global _HOT_CONCEPTS_RESULT
    import json
    import re
    from curl_cffi import requests as cr

    try:
        url = "http://money.finance.sina.com.cn/q/view/newFLJK.php"
        r = cr.get(url, params={"param": "industry", "client": "autocallidentifykey="}, timeout=15, impersonate="chrome120")
        if r.status_code != 200:
            return []

        text = r.text
        json_start = text.find("{", text.find("var S_Finance_bankuai_industry"))
        json_end = text.rfind("}")
        data = json.loads(text[json_start : json_end + 1])

        sectors = []
        for v in data.values():
            parts = v.split(",")
            if len(parts) >= 5:
                try:
                    change = float(parts[4]) if parts[4] else 0.0
                except ValueError:
                    change = 0.0
                sectors.append({
                    "板块名称": parts[1],
                    "涨跌幅": change,
                })

        sectors.sort(key=lambda x: x["涨跌幅"], reverse=True)
        return sectors[:top_n]
    except Exception:
        return []


def _calculate_ma(kline: list[dict]) -> dict:
    """Calculate moving averages from kline data."""
    if len(kline) < 5:
        return {}
    closes = [d["收盘"] for d in kline]
    return {
        "MA5": sum(closes[-5:]) / 5 if len(closes) >= 5 else None,
        "MA20": sum(closes[-20:]) / 20 if len(closes) >= 20 else None,
        "MA60": sum(closes[-60:]) / 60 if len(closes) >= 60 else None,
    }


# Tech factor extension: objective indicator layer for trend, momentum, reversal,
# volume, risk, and breakout signals before the LLM makes a structured judgment.
def _safe_float(value, default: float = 0.0) -> float:
    """Convert akshare/numpy values to float safely for indicator calculations."""
    try:
        if value is None:
            return default
        return float(value)
    except (TypeError, ValueError):
        return default


def _pct_change(current: float, previous: float | None) -> float | None:
    """Return percentage change, guarding against missing or zero denominators."""
    if previous is None or previous == 0:
        return None
    return (current / previous - 1) * 100


def _max_drawdown(values: list[float]) -> float | None:
    """Calculate max drawdown in percent over a price series."""
    if not values:
        return None
    peak = values[0]
    max_dd = 0.0
    for value in values:
        peak = max(peak, value)
        if peak:
            max_dd = min(max_dd, value / peak - 1)
    return max_dd * 100


def _calculate_rsi(closes: list[float], period: int = 14) -> float | None:
    """Calculate simple RSI for the tech reversal factor."""
    if len(closes) <= period:
        return None
    deltas = [closes[i] - closes[i - 1] for i in range(1, len(closes))]
    recent = deltas[-period:]
    gains = [max(delta, 0) for delta in recent]
    losses = [abs(min(delta, 0)) for delta in recent]
    avg_gain = sum(gains) / period
    avg_loss = sum(losses) / period
    if avg_gain == 0 and avg_loss == 0:
        return 50.0
    if avg_loss == 0:
        return 100.0
    return 100 - (100 / (1 + avg_gain / avg_loss))


def _annualized_volatility(closes: list[float], period: int = 20) -> float | None:
    """Calculate annualized volatility from daily returns."""
    if len(closes) <= period:
        return None
    returns = []
    recent = closes[-(period + 1):]
    for i in range(1, len(recent)):
        prev = recent[i - 1]
        if prev:
            returns.append(recent[i] / prev - 1)
    if len(returns) < 2:
        return None
    mean = sum(returns) / len(returns)
    variance = sum((ret - mean) ** 2 for ret in returns) / (len(returns) - 1)
    return (variance ** 0.5) * (252 ** 0.5) * 100


def _calculate_technical_indicators(kline: list[dict]) -> dict:
    """Calculate the expanded tech factor set requested for technical analysis."""
    if len(kline) < 5:
        return {}

    closes = [_safe_float(d.get("收盘")) for d in kline]
    volumes = [_safe_float(d.get("成交量")) for d in kline]
    amounts = [_safe_float(d.get("成交额")) for d in kline]
    latest_close = closes[-1]
    ma = _calculate_ma(kline)

    def avg_last(values: list[float], period: int) -> float | None:
        if len(values) < period:
            return None
        return sum(values[-period:]) / period

    ma5 = ma.get("MA5")
    ma20 = ma.get("MA20")
    ma60 = ma.get("MA60")
    high20 = max(closes[-20:]) if len(closes) >= 20 else None
    high60 = max(closes[-60:]) if len(closes) >= 60 else None
    avg_volume_5 = avg_last(volumes, 5)
    avg_volume_20 = avg_last(volumes, 20)
    avg_amount_5 = avg_last(amounts, 5)
    prev_amount_5 = sum(amounts[-10:-5]) / 5 if len(amounts) >= 10 else None

    return {
        "latest_close": latest_close,
        "MA5": ma5,
        "MA20": ma20,
        "MA60": ma60,
        "close_vs_ma5": _pct_change(latest_close, ma5),
        "close_vs_ma20": _pct_change(latest_close, ma20),
        "close_vs_ma60": _pct_change(latest_close, ma60),
        "return_5d": _pct_change(latest_close, closes[-6] if len(closes) >= 6 else None),
        "return_20d": _pct_change(latest_close, closes[-21] if len(closes) >= 21 else None),
        "return_60d": _pct_change(latest_close, closes[-61] if len(closes) >= 61 else None),
        "RSI14": _calculate_rsi(closes, period=14),
        "BIAS5": _pct_change(latest_close, ma5),
        "BIAS20": _pct_change(latest_close, ma20),
        "volume_ratio_5_20": (avg_volume_5 / avg_volume_20) if avg_volume_5 and avg_volume_20 else None,
        "amount_change_5d": _pct_change(avg_amount_5, prev_amount_5),
        "volatility_20d": _annualized_volatility(closes, period=20),
        "max_drawdown_60d": _max_drawdown(closes[-60:]) if len(closes) >= 60 else None,
        "is_20d_high": bool(high20 is not None and latest_close >= high20),
        "is_60d_high": bool(high60 is not None and latest_close >= high60),
        "distance_to_20d_high": _pct_change(latest_close, high20),
        "distance_to_60d_high": _pct_change(latest_close, high60),
    }


def _format_technical_indicators(indicators: dict) -> str:
    """Format expanded tech indicators by category for prompt injection."""
    def fmt(value, suffix: str = "") -> str:
        if value is None:
            return "N/A"
        if isinstance(value, bool):
            return "Yes" if value else "No"
        if isinstance(value, (int, float)):
            return f"{value:.2f}{suffix}"
        return str(value)

    return "\n".join([
        "Trend:",
        f"- Latest close: {fmt(indicators.get('latest_close'))}",
        f"- MA5 / MA20 / MA60: {fmt(indicators.get('MA5'))} / {fmt(indicators.get('MA20'))} / {fmt(indicators.get('MA60'))}",
        f"- Close vs MA5 / MA20 / MA60: {fmt(indicators.get('close_vs_ma5'), '%')} / {fmt(indicators.get('close_vs_ma20'), '%')} / {fmt(indicators.get('close_vs_ma60'), '%')}",
        "Momentum:",
        f"- 5d / 20d / 60d return: {fmt(indicators.get('return_5d'), '%')} / {fmt(indicators.get('return_20d'), '%')} / {fmt(indicators.get('return_60d'), '%')}",
        "Reversal:",
        f"- RSI14: {fmt(indicators.get('RSI14'))}",
        f"- BIAS5 / BIAS20: {fmt(indicators.get('BIAS5'), '%')} / {fmt(indicators.get('BIAS20'), '%')}",
        "Volume:",
        f"- 5d vs 20d volume ratio: {fmt(indicators.get('volume_ratio_5_20'))}",
        f"- 5d average amount change: {fmt(indicators.get('amount_change_5d'), '%')}",
        "Risk:",
        f"- 20d annualized volatility: {fmt(indicators.get('volatility_20d'), '%')}",
        f"- 60d max drawdown: {fmt(indicators.get('max_drawdown_60d'), '%')}",
        "Breakout:",
        f"- 20d high / 60d high: {fmt(indicators.get('is_20d_high'))} / {fmt(indicators.get('is_60d_high'))}",
        f"- Distance to 20d / 60d high: {fmt(indicators.get('distance_to_20d_high'), '%')} / {fmt(indicators.get('distance_to_60d_high'), '%')}",
    ])


def _load_prompt(prompt_name: str) -> str:
    """Load a prompt markdown file from the prompts/ directory."""
    module_dir = Path(__file__).parent.parent
    prompt_path = module_dir / "prompts" / f"{prompt_name}.md"
    if not prompt_path.exists():
        return ""
    return prompt_path.read_text(encoding="utf-8")


_ALLOWED_FACTOR_KEYS = {"technical", "fundamental", "capital", "sentiment"}
_FACTOR_LABELS = {
    "technical": "技术面",
    "fundamental": "基本面",
    "capital": "资金面",
    "sentiment": "情绪面",
}


def _get_state_config(state: AgentState | dict | None) -> dict:
    """Return per-request config stored in AgentState.config."""
    if not state:
        return {}
    if isinstance(state, dict):
        config = state.get("config") or {}
    else:
        config = getattr(state, "config", None) or {}
    return config if isinstance(config, dict) else {}


def _get_selected_factors(state: AgentState | dict | None) -> list[str] | None:
    """Read and validate selected factor keys from frontend/API config."""
    config = _get_state_config(state)
    raw = config.get("selected_factors")
    if raw is None:
        return None
    if isinstance(raw, str):
        raw_items = [item.strip() for item in raw.split(",")]
    elif isinstance(raw, (list, tuple, set)):
        raw_items = list(raw)
    else:
        return None

    selected: list[str] = []
    for item in raw_items:
        key = str(item).strip()
        if key in _ALLOWED_FACTOR_KEYS and key not in selected:
            selected.append(key)
    return selected or None


def _load_prompt_with_append(prompt_name: str, state: AgentState | dict | None = None) -> str:
    """
    Load default prompt and append per-request prompt additions.

    The default prompts/*.md files are never modified. The frontend can send
    prompt_append.global and prompt_append.<prompt_name> for this request only.
    """
    default_prompt = _load_prompt(prompt_name)
    config = _get_state_config(state)
    prompt_append = config.get("prompt_append") or {}
    if not isinstance(prompt_append, dict):
        return default_prompt

    global_append = str(prompt_append.get("global") or "").strip()
    specific_append = str(prompt_append.get(prompt_name) or "").strip()

    result = default_prompt
    if global_append:
        result += "\n\n【用户追加的全局 system prompt】\n" + global_append
    if specific_append:
        result += f"\n\n【用户追加到 {prompt_name}.md 的 system prompt】\n" + specific_append
    return result


def _parse_json_from_llm(text: str) -> dict:
    """Extract JSON from LLM response, handling markdown code blocks."""
    text = text.strip()
    if text.startswith("```"):
        lines = text.split("\n")
        if lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].startswith("```"):
            lines = lines[:-1]
        text = "\n".join(lines).strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        start = text.find("{")
        end = text.rfind("}")
        if start != -1 and end != -1:
            return json.loads(text[start : end + 1])
        raise


# =============================================================================
# Phase 1 Nodes: Intent & Market Structure
# =============================================================================


def intent_clarification_node(state: AgentState, planner: BasePlanner) -> dict:
    """Parse the user's natural language query into structured intent."""
    log_node_start("intent_clarification_node", {"query": state["query"][:50]})

    query = state["query"]
    system_prompt = _load_prompt_with_append("intent_system", state)
    user_prompt = _load_prompt("intent_user").format(query=query)

    try:
        response_text = planner.generate(system_prompt, user_prompt)
        data = _parse_json_from_llm(response_text)
        intent = UserIntent(**data)
    except Exception as e:
        log_error("intent_clarification", RuntimeError(f"Failed to parse intent: {e}"))
        intent = UserIntent(
            stock_name=query.replace("帮我看看", "").replace("怎么样", "").strip(),
            clarified_query=query,
        )

    if not intent.stock_code and intent.stock_name:
        intent.stock_code = _resolve_stock_code(intent.stock_name)

    log_node_end(
        "intent_clarification_node",
        {
            "stock": intent.stock_name,
            "code": intent.stock_code,
            "intent": intent.intent_type,
            "horizon": intent.time_horizon,
        },
    )
    log_info("intent", {"stock": intent.stock_name, "code": intent.stock_code})
    return {"user_intent": intent}


def market_structure_node(state: AgentState, planner: BasePlanner) -> dict:
    """Analyze the stock's position in the current market landscape."""
    log_node_start("market_structure_node")

    intent = state.get("user_intent")
    if not intent:
        log_error("market_structure", RuntimeError("No user_intent in state"))
        return {"status": AgentStatus.FAILED, "error_message": "Missing user_intent"}

    stock_code = intent.stock_code
    stock_name = intent.stock_name
    if not stock_code:
        return {
            "status": AgentStatus.FAILED,
            "error_message": f"无法解析股票代码: {stock_name}",
        }

    basic_info = _fetch_stock_basic(stock_code)
    kline_data = _fetch_recent_kline(stock_code, days=10)
    hot_concepts = _fetch_hot_concepts(top_n=10)

    kline_summary = ""
    if kline_data:
        latest = kline_data[-1]
        kline_summary = (
            f"最新收盘价: {latest['收盘']}, 最新涨跌幅: {latest['涨跌幅']}%\n"
            f"近{len(kline_data)}日走势: "
            + " → ".join([f"{d['收盘']}({d['涨跌幅']}%)" for d in kline_data[-5:]])
        )

    hot_concepts_text = "\n".join(
        [f"- {c['板块名称']}: {c['涨跌幅']}%" for c in hot_concepts]
    )

    system_prompt = _load_prompt_with_append("market_structure_system", state)
    user_prompt = _load_prompt("market_structure_user").format(
        stock_name=basic_info.get("股票简称", stock_name),
        stock_code=stock_code,
        industry=basic_info.get("行业", "未知"),
        concepts=basic_info.get("概念", "暂无"),
        hot_sectors=hot_concepts_text,
        sector_heat_rank="前10热点" if hot_concepts else "未知",
        change_5d=latest.get("涨跌幅", 0) if kline_data else 0,
        sector_change_5d=0,
        kline_summary=kline_summary,
    )

    try:
        response_text = planner.generate(system_prompt, user_prompt)
        data = _parse_json_from_llm(response_text)
        market_structure = MarketStructure(**data)
    except Exception as e:
        log_error("market_structure", RuntimeError(f"Planner analysis failed: {e}"))
        market_structure = MarketStructure(
            current_market_themes=[c["板块名称"] for c in hot_concepts[:3]],
            stock_themes=[basic_info.get("行业", "")],
            theme_position="未知",
            analysis_summary=f"{stock_name}({stock_code})，行业{basic_info.get('行业', '未知')}，数据获取完成但分析失败。",
        )

    evidence = EvidenceItem(
        source="market_structure",
        content=market_structure.analysis_summary,
        evidence_type="structured",
        confidence=0.75,
        metadata={"stock_code": stock_code, "industry": basic_info.get("行业", "")},
    )

    log_node_end("market_structure_node", {"position": market_structure.theme_position})
    return {"market_structure": market_structure, "evidence_log": [evidence]}


# =============================================================================
# Phase 2 Nodes: Sector Router & Factor Analysis
# =============================================================================


def sector_router_node(state: AgentState, planner: BasePlanner) -> dict:
    """
    Dynamically decide which factor sectors to analyze.

    Based on user intent and market structure.
    """
    log_node_start("sector_router_node")

    intent = state.get("user_intent")
    market = state.get("market_structure")

    if not intent:
        log_error("sector_router", RuntimeError("No user_intent in state"))
        return {"status": AgentStatus.FAILED, "error_message": "Missing user_intent"}

    selected_factors = _get_selected_factors(state)
    if selected_factors is not None:
        skip_reasons = {
            key: "用户在前端未选择该因子"
            for key in _ALLOWED_FACTOR_KEYS
            if key not in selected_factors
        }
        route = SectorRoute(
            sectors=selected_factors,
            skip_reasons=skip_reasons,
            analysis_focus="根据用户在前端选择的因子进行分析",
        )
        log_node_end("sector_router_node", {"sectors": route.sectors, "source": "frontend"})
        log_info("sector_router", {"sectors": route.sectors, "focus": route.analysis_focus, "source": "frontend"})
        return {"sector_route": route}

    system_prompt = _load_prompt_with_append("sector_route_system", state)
    user_prompt = _load_prompt("sector_route_user").format(
        stock_name=intent.stock_name,
        stock_code=intent.stock_code,
        intent_type=intent.intent_type,
        time_horizon=intent.time_horizon,
        risk_preference=intent.risk_preference,
        clarified_query=intent.clarified_query,
        theme_position=market.theme_position if market else "未知",
        stock_themes=", ".join(market.stock_themes) if market else "未知",
        market_themes=", ".join(market.current_market_themes) if market else "未知",
        market_sentiment=market.market_sentiment if market else "未知",
    )

    try:
        response_text = planner.generate(system_prompt, user_prompt)
        data = _parse_json_from_llm(response_text)
        route = SectorRoute(**data)
    except Exception as e:
        log_error("sector_router", RuntimeError(f"Routing failed: {e}"))
        # Default: analyze all sectors
        route = SectorRoute(
            sectors=["technical", "fundamental", "capital", "sentiment"],
            analysis_focus="全面分析",
        )

    log_node_end("sector_router_node", {"sectors": route.sectors})
    log_info("sector_router", {"sectors": route.sectors, "focus": route.analysis_focus})
    return {"sector_route": route}


def _should_analyze(state: AgentState, sector: str) -> bool:
    """Check if a sector should be analyzed based on frontend selection or route."""
    selected_factors = _get_selected_factors(state)
    if selected_factors is not None:
        return sector in selected_factors

    route = state.get("sector_route")
    if not route:
        return True  # Default: analyze all if no route
    return sector in route.sectors


def _factor_evidence_to_dict(evidence: FactorEvidence | None) -> str:
    """Format FactorEvidence for prompt injection."""
    if not evidence:
        return "未分析"
    return (
        f"趋势信号: {evidence.trend_signal}, 评分: {evidence.score}/100\n"
        f"关键发现: {', '.join(evidence.key_findings)}\n"
        f"风险标记: {', '.join(evidence.risk_flags) if evidence.risk_flags else '无'}"
    )


def technical_analysis_node(state: AgentState, planner: BasePlanner) -> dict:
    """Technical factor analysis: K-line, MA, MACD, RSI, volume."""
    log_node_start("technical_analysis_node")

    if not _should_analyze(state, "technical"):
        log_info("technical_analysis", {"status": "skipped"})
        return {"technical_evidence": None}

    intent = state.get("user_intent")
    stock_code = intent.stock_code if intent else ""
    stock_name = intent.stock_name if intent else ""

    # Tech factor extension: use a longer window so MA60, 60d return, drawdown, and highs are available.
    kline = _fetch_recent_kline(stock_code, days=80)
    indicators = _calculate_technical_indicators(kline)

    kline_text = "\n".join(
        [
            f"  {d['日期']}: 收{d['收盘']} 涨跌{d['涨跌幅']}% 量{d['成交量']}"
            for d in kline[-10:]
        ]
    )
    # Tech factor extension: format the expanded indicator set instead of the old MA-only summary.
    indicator_text = _format_technical_indicators(indicators)

    system_prompt = _load_prompt_with_append("technical_system", state)
    user_prompt = _load_prompt("technical_user").format(
        stock_name=stock_name,
        stock_code=stock_code,
        kline_summary=kline_text,
        indicator_summary=indicator_text,
    )

    try:
        response_text = planner.generate(system_prompt, user_prompt)
        try:
            data = _parse_json_from_llm(response_text)
        except json.JSONDecodeError as parse_error:
            log_error(
                "technical_analysis_parse",
                RuntimeError(
                    f"Failed to parse technical JSON: {parse_error}; "
                    f"raw_response_preview={response_text[:500]!r}"
                ),
            )
            raise
        evidence = FactorEvidence(**data)
    except Exception as e:
        log_error("technical_analysis", RuntimeError(f"Analysis failed: {e}"))
        evidence = FactorEvidence(
            factor_name="technical",
            trend_signal="Neutral",
            score=50,
            key_findings=["数据获取或分析失败"],
        )

    item = EvidenceItem(
        source="technical",
        content=evidence.raw_data_summary or "技术面分析",
        evidence_type="score",
        score=evidence.score,
        confidence=0.7,
    )

    log_node_end(
        "technical_analysis_node",
        {"score": evidence.score, "signal": evidence.trend_signal},
    )
    return {"technical_evidence": evidence, "evidence_log": [item]}


def fundamental_analysis_node(state: AgentState, planner: BasePlanner) -> dict:
    """Fundamental factor analysis: PE, PB, ROE, financial health."""
    log_node_start("fundamental_analysis_node")

    if not _should_analyze(state, "fundamental"):
        log_info("fundamental_analysis", {"status": "skipped"})
        return {"fundamental_evidence": None}

    intent = state.get("user_intent")
    stock_code = intent.stock_code if intent else ""
    stock_name = intent.stock_name if intent else ""

    basic = _fetch_stock_basic(stock_code)
    valuation = _fetch_valuation(stock_code)
    if "总市值" not in valuation and basic.get("总市值") is not None:
        valuation["总市值"] = basic.get("总市值")

    reports = _fetch_financial_reports(stock_code)
    metrics = _calculate_fundamental_metrics(reports, valuation, basic)
    industry = metrics.get("industry", basic.get("行业", "未知"))
    fundamental_text = _format_fundamental_metrics(metrics)

    system_prompt = _load_prompt_with_append("fundamental_system", state)
    user_prompt = _load_prompt("fundamental_user").format(
        stock_name=stock_name,
        stock_code=stock_code,
        industry=industry,
        fundamental_data=fundamental_text,
    )

    try:
        response_text = planner.generate(system_prompt, user_prompt)
        data = _parse_json_from_llm(response_text)
        evidence = FactorEvidence(**data)
    except Exception as e:
        log_error("fundamental_analysis", RuntimeError(f"Analysis failed: {e}"))
        evidence = FactorEvidence(
            factor_name="fundamental",
            trend_signal="Neutral",
            score=50,
            key_findings=["基本面数据获取或分析失败"],
        )

    item = EvidenceItem(
        source="fundamental",
        content=evidence.raw_data_summary or "基本面分析",
        evidence_type="score",
        score=evidence.score,
        confidence=0.7,
    )

    log_node_end("fundamental_analysis_node", {"score": evidence.score})
    return {"fundamental_evidence": evidence, "evidence_log": [item]}



def _state_get(state: Any, key: str, default: Any = None) -> Any:
    """
    兼容 dict / pydantic / dataclass 类型的 AgentState。
    """
    if isinstance(state, dict):
        return state.get(key, default)
    return getattr(state, key, default)


def _load_prompt_file(path: str) -> str:
    """
    Load a prompt file. Relative paths are resolved from the project root.
    """
    try:
        prompt_path = Path(path)
        if not prompt_path.is_absolute():
            prompt_path = Path(__file__).parent.parent / prompt_path
        return prompt_path.read_text(encoding="utf-8")
    except Exception:
        return ""


def _parse_json_loose(text: Any) -> dict[str, Any]:
    """
    尽量从 LLM 返回中解析 JSON。
    """
    if isinstance(text, dict):
        return text

    if hasattr(text, "content"):
        text = text.content

    if text is None:
        return {}

    s = str(text).strip()

    if s.startswith("```"):
        lines = s.split("\n")
        if lines and lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].startswith("```"):
            lines = lines[:-1]
        s = "\n".join(lines).strip()

    try:
        return json.loads(s)
    except Exception:
        pass

    start = s.find("{")
    end = s.rfind("}")
    if start >= 0 and end > start:
        try:
            return json.loads(s[start : end + 1])
        except Exception:
            return {}

    return {}


def _render_capital_user_prompt(template: str, **kwargs: Any) -> str:
    """
    用简单 replace 渲染资金因子 prompt，避免 .format() 被 JSON 大括号干扰。
    """
    text = template
    for key, value in kwargs.items():
        text = text.replace("{" + key + "}", str(value))
    return text


def _call_planner_for_capital(
    planner: Any, system_prompt: str, user_prompt: str
) -> dict[str, Any]:
    """
    调用 LLM 解释资金因子。如果调用失败，返回空 dict，不影响 workflow。
    """
    if planner is None:
        return {}

    prompt = f"{system_prompt}\n\n{user_prompt}"

    try:
        # 项目原 BasePlanner 接口
        if hasattr(planner, "generate"):
            resp = planner.generate(system_prompt, user_prompt)
            return _parse_json_loose(resp)

        # 兼容其他常见接口
        if hasattr(planner, "invoke"):
            resp = planner.invoke(prompt)
            return _parse_json_loose(resp)

        if hasattr(planner, "llm") and hasattr(planner.llm, "invoke"):
            resp = planner.llm.invoke(prompt)
            return _parse_json_loose(resp)

        if hasattr(planner, "chat"):
            resp = planner.chat(prompt)
            return _parse_json_loose(resp)

        if hasattr(planner, "complete"):
            resp = planner.complete(prompt)
            return _parse_json_loose(resp)

    except Exception as e:
        log_error("capital_planner", RuntimeError(f"Planner call failed: {e}"))
        return {}

    return {}


def _capital_fallback_evidence(
    stock_name: str,
    stock_code: str,
    message: str,
    confidence: float = 0.30,
) -> dict:
    """
    构造资金因子兜底返回，保证 workflow 不会因 capital 节点失败而中断。
    """
    indicators = {
        "data_available": False,
        "data_quality": "failed",
        "warnings": [message],
    }

    evidence = build_capital_evidence(
        stock_name=str(stock_name or stock_code or "UNKNOWN"),
        stock_code=str(stock_code or "UNKNOWN"),
        indicators=indicators,
        llm_result=None,
    )

    item = EvidenceItem(
        source="capital",
        content=evidence.raw_data_summary or message,
        evidence_type="score",
        score=evidence.score,
        confidence=confidence,
    )

    return {
        "capital_evidence": evidence,
        "evidence_log": [item],
    }


def capital_analysis_node(state: AgentState, planner: BasePlanner) -> dict:
    """
    Capital factor analysis node.

    Contract:
    - input: AgentState + BasePlanner
    - output: {"capital_evidence": FactorEvidence, "evidence_log": [EvidenceItem]}
    """
    log_node_start("capital_analysis_node")

    try:
        if not _should_analyze(state, "capital"):
            log_info("capital_analysis", {"status": "skipped"})
            log_node_end("capital_analysis_node", {"status": "skipped"})
            return {"capital_evidence": None}
    except Exception:
        # 如果路由信息异常，不阻断资金因子；默认继续分析。
        pass

    intent_obj = _state_get(state, "user_intent", None)

    stock_code = (
        _state_get(state, "stock_code", None)
        or getattr(intent_obj, "stock_code", None)
        or ""
    )
    stock_name = (
        _state_get(state, "stock_name", None)
        or getattr(intent_obj, "stock_name", None)
        or stock_code
    )
    user_intent = (
        getattr(intent_obj, "intent_type", None)
        or _state_get(state, "intent_type", None)
        or "analysis"
    )
    time_horizon = (
        _state_get(state, "time_horizon", None)
        or getattr(intent_obj, "time_horizon", None)
        or "medium"
    )
    market_structure = _state_get(state, "market_structure", None)

    if not stock_code:
        result = _capital_fallback_evidence(
            stock_name=str(stock_name or "UNKNOWN"),
            stock_code="UNKNOWN",
            message="AgentState 中缺少 stock_code，无法执行资金因子分析。",
            confidence=0.30,
        )
        evidence = result["capital_evidence"]
        log_node_end(
            "capital_analysis_node",
            {"score": evidence.score, "status": "missing_stock_code"},
        )
        return result

    try:
        # 1. AkShare 数据获取
        flow_df = fetch_capital_flow(str(stock_code))
        rank_df = fetch_fund_flow_rank(str(stock_code), indicator="5日")
        margin_df = fetch_margin_data(str(stock_code))

        # 2. 资金指标计算
        indicators = calculate_capital_indicators(
            flow_df=flow_df,
            margin_df=margin_df,
            rank_df=rank_df,
        )

        # 3. 构造 LLM prompt 数据
        capital_prompt_data = build_capital_prompt_data(indicators)

        system_prompt = _load_prompt_with_append("capital_system", state)
        user_template = _load_prompt_file("prompts/capital_user.md")

        if not system_prompt:
            system_prompt = "你是资金因子分析助手。只能基于给定结构化数据解释，不得编造不存在的数据。"

        if user_template:
            user_prompt = _render_capital_user_prompt(
                user_template,
                stock_name=stock_name,
                stock_code=stock_code,
                user_intent=user_intent,
                time_horizon=time_horizon,
                market_structure=market_structure,
                capital_indicators=capital_prompt_data,
            )
        else:
            user_prompt = f"""
请基于以下结构化资金因子数据，输出 JSON。

股票：{stock_name}（{stock_code}）
用户意图：{user_intent}
分析周期：{time_horizon}
市场结构：{market_structure}

资金因子数据：
{capital_prompt_data}
"""

        # 4. LLM 解释。失败时返回空 dict，后续仍使用规则评分结果。
        llm_result = _call_planner_for_capital(planner, system_prompt, user_prompt)

        # 5. 构造 FactorEvidence
        evidence = build_capital_evidence(
            stock_name=str(stock_name),
            stock_code=str(stock_code),
            indicators=indicators,
            llm_result=llm_result,
        )

        # 6. 动态置信度，用 EvidenceItem 传给 workflow
        confidence = 0.70
        if indicators.get("data_available"):
            confidence += 0.10
        if indicators.get("rank_available"):
            confidence += 0.05
        if indicators.get("margin_available"):
            confidence += 0.05
        if indicators.get("warnings"):
            confidence -= 0.15
        confidence = max(0.30, min(0.90, confidence))

        item = EvidenceItem(
            source="capital",
            content=evidence.raw_data_summary or "资金面分析",
            evidence_type="score",
            score=evidence.score,
            confidence=confidence,
        )

        log_node_end(
            "capital_analysis_node",
            {"score": evidence.score, "signal": evidence.trend_signal},
        )

        return {
            "capital_evidence": evidence,
            "evidence_log": [item],
        }

    except Exception as e:
        log_error("capital_analysis", RuntimeError(f"Analysis failed: {e}"))

        result = _capital_fallback_evidence(
            stock_name=str(stock_name),
            stock_code=str(stock_code),
            message=f"资金因子节点执行失败，已返回中性兜底结果: {str(e)}",
            confidence=0.30,
        )
        evidence = result["capital_evidence"]
        log_node_end(
            "capital_analysis_node",
            {"score": evidence.score, "status": "fallback"},
        )
        return result


def sentiment_analysis_node(state: AgentState, planner: BasePlanner) -> dict:
    """Sentiment factor analysis with dynamic branching based on time horizon.

    Branch A (short-term / speculative): focuses on hot money, dragon tiger list,
        popularity ranking, and event catalysts.
    Branch B (mid/long-term / fundamental): focuses on macro industry trends,
        policy narrative, and institutional sentiment.
    Falls back to the original sentiment_system prompt if a branch prompt is missing.
    """
    log_node_start("sentiment_analysis_node")

    if not _should_analyze(state, "sentiment"):
        log_info("sentiment_analysis", {"status": "skipped"})
        return {"sentiment_evidence": None}

    intent = state.get("user_intent")
    stock_code = intent.stock_code if intent else ""
    stock_name = intent.stock_name if intent else ""
    time_horizon = intent.time_horizon if intent else "medium"

    # --- Common data (shared by both branches) ---
    news = _fetch_news(stock_code, top_n=10)
    news_text = (
        "\n".join([f"  [{d['发布时间']}] {d['新闻标题']}" for d in news])
        if news
        else "暂无新闻"
    )

    hot_concepts = _fetch_hot_concepts(top_n=10)
    concept_text = "\n".join(
        [f"  {c['板块名称']}: {c['涨跌幅']}%" for c in hot_concepts]
    )

    # --- Dynamic branching ---
    if time_horizon == "short":
        # Branch A: Short-term / Speculative scenario
        log_info("sentiment_analysis", {"branch": "short_term"})
        longhubang = _fetch_longhubang(stock_code)
        lhb_text = "\n".join([
            f"  {d.get('名称', stock_name)}: 上榜原因={d.get('上榜原因', 'N/A')}, "
            f"买入额={d.get('买入额', 'N/A')}, 卖出额={d.get('卖出额', 'N/A')}, "
            f"净买入额={d.get('净买入额', 'N/A')}"
            for d in longhubang
        ]) if longhubang else "未上龙虎榜"

        hot_rank = _fetch_stock_hot_rank(stock_code)
        rank_text = f"人气排名: {hot_rank.get('人气排名', 'N/A')}" if hot_rank else "无人气排名数据"

        sentiment_text = (
            f"近期新闻:\n{news_text}\n\n"
            f"热点板块:\n{concept_text}\n\n"
            f"龙虎榜数据:\n{lhb_text}\n\n"
            f"个股热度:\n{rank_text}"
        )

        branch_prompt = _load_prompt_with_append("sentiment_short_term", state)
        system_prompt = branch_prompt if branch_prompt else _load_prompt_with_append("sentiment_system", state)
    else:
        # Branch B: Mid-to-Long term / Fundamental scenario (default)
        log_info("sentiment_analysis", {"branch": "long_term"})
        industry_sectors = _fetch_industry_sectors(top_n=10)
        industry_text = "\n".join([
            f"  {s.get('板块名称', 'N/A')}: {s.get('涨跌幅', 'N/A')}%"
            for s in industry_sectors
        ]) if industry_sectors else "暂无行业板块数据"

        sentiment_text = (
            f"近期新闻:\n{news_text}\n\n"
            f"热点板块:\n{concept_text}\n\n"
            f"行业板块行情:\n{industry_text}"
        )

        branch_prompt = _load_prompt_with_append("sentiment_long_term", state)
        system_prompt = branch_prompt if branch_prompt else _load_prompt_with_append("sentiment_system", state)

    user_prompt = _load_prompt("sentiment_user").format(
        stock_name=stock_name,
        stock_code=stock_code,
        stock_themes=", ".join(
            state.get("market_structure", MarketStructure()).stock_themes
        ),
        sentiment_data=sentiment_text,
    )

    try:
        response_text = planner.generate(system_prompt, user_prompt)
        data = _parse_json_from_llm(response_text)
        evidence = FactorEvidence(**data)
    except Exception as e:
        log_error("sentiment_analysis", RuntimeError(f"Analysis failed: {e}"))
        evidence = FactorEvidence(
            factor_name="sentiment",
            trend_signal="中性",
            score=50,
            key_findings=["情绪面数据获取或分析失败"],
        )

    item = EvidenceItem(
        source="sentiment",
        content=evidence.raw_data_summary or "情绪面分析",
        evidence_type="score",
        score=evidence.score,
        confidence=0.6,
    )

    log_node_end("sentiment_analysis_node", {"score": evidence.score, "branch": "short" if time_horizon == "short" else "long"})
    return {"sentiment_evidence": evidence, "evidence_log": [item]}


# =============================================================================
# Phase 2 Nodes: Cross-Sector Fusion & Final Answer
# =============================================================================


def cross_sector_fusion_node(state: AgentState, planner: BasePlanner) -> dict:
    """
    Synthesize evidence from all factor analyses into a unified assessment.
    """
    log_node_start("cross_sector_fusion_node")

    intent = state.get("user_intent")
    tech = state.get("technical_evidence")
    fund = state.get("fundamental_evidence")
    cap = state.get("capital_evidence")
    sent = state.get("sentiment_evidence")

    system_prompt = _load_prompt_with_append("fusion_system", state)
    user_prompt = _load_prompt("fusion_user").format(
        stock_name=intent.stock_name if intent else "",
        stock_code=intent.stock_code if intent else "",
        time_horizon=intent.time_horizon if intent else "medium",
        technical_evidence=_factor_evidence_to_dict(tech),
        fundamental_evidence=_factor_evidence_to_dict(fund),
        capital_evidence=_factor_evidence_to_dict(cap),
        sentiment_evidence=_factor_evidence_to_dict(sent),
    )

    try:
        response_text = planner.generate(system_prompt, user_prompt)
        data = _parse_json_from_llm(response_text)
        assessment = CompositeAssessment(**data)
    except Exception as e:
        log_error("cross_sector_fusion", RuntimeError(f"Fusion failed: {e}"))
        # Calculate simple average score
        scores = [e.score for e in [tech, fund, cap, sent] if e]
        avg_score = int(sum(scores) / len(scores)) if scores else 50
        assessment = CompositeAssessment(
            composite_score=avg_score,
            trend_direction="震荡",
            position_status="震荡",
            risk_level="中",
            summary="综合分析失败，使用默认评估。",
        )

    evidence = EvidenceItem(
        source="cross_sector_fusion",
        content=assessment.summary,
        evidence_type="structured",
        score=assessment.composite_score,
        confidence=0.75,
    )

    log_node_end(
        "cross_sector_fusion_node",
        {
            "score": assessment.composite_score,
            "trend": assessment.trend_direction,
            "risk": assessment.risk_level,
        },
    )
    return {"composite_assessment": assessment, "evidence_log": [evidence]}


def final_answer_node(state: AgentState, planner: BasePlanner) -> dict:
    """Generate the final structured report."""
    log_node_start("final_answer_node")

    intent = state.get("user_intent")
    market = state.get("market_structure")
    route = state.get("sector_route")
    tech = state.get("technical_evidence")
    fund = state.get("fundamental_evidence")
    cap = state.get("capital_evidence")
    sent = state.get("sentiment_evidence")
    composite = state.get("composite_assessment")
    evidence_items = state.get("evidence_log", [])

    lines = []
    lines.append("=" * 50)
    lines.append(
        f"个股预测分析系统 - {intent.stock_name if intent else '股票'} 分析报告"
    )
    lines.append("=" * 50)
    lines.append("")

    if intent:
        lines.append("【用户意图】")
        lines.append(f"股票：{intent.stock_name} ({intent.stock_code})")
        lines.append(f"分析类型：{intent.intent_type} | 周期：{intent.time_horizon}")
        lines.append(f"风险偏好：{intent.risk_preference}")
        lines.append("")

    if market:
        lines.append("【市场结构定位】")
        lines.append(f"当前市场主线：{', '.join(market.current_market_themes)}")
        lines.append(f"股票所属主线：{', '.join(market.stock_themes)}")
        lines.append(f"主线内位置：{market.theme_position}")
        lines.append(f"市场情绪：{market.market_sentiment}")
        lines.append("")

    if route:
        lines.append("【分析范围】")
        lines.append(f"选中的因子：{', '.join(route.sectors)}")
        lines.append(f"分析重点：{route.analysis_focus}")
        lines.append("")

    lines.append("【四大因子分析】")
    for name, ev in [
        ("技术面", tech),
        ("基本面", fund),
        ("资金面", cap),
        ("情绪面", sent),
    ]:
        if ev:
            lines.append(f"  {name}: {ev.trend_signal} (评分: {ev.score}/100)")
            for finding in ev.key_findings:
                lines.append(f"    - {finding}")
            if ev.risk_flags:
                lines.append(f"    风险: {', '.join(ev.risk_flags)}")
        else:
            lines.append(f"  {name}: 未分析")
    lines.append("")

    if composite:
        lines.append("【综合评估】")
        lines.append(f"综合评分：{composite.composite_score}/100")
        lines.append(f"趋势方向：{composite.trend_direction}")
        lines.append(f"位置状态：{composite.position_status}")
        lines.append(f"风险等级：{composite.risk_level}")
        if composite.risk_details:
            lines.append(f"风险详情：{', '.join(composite.risk_details)}")
        lines.append(f"评估摘要：{composite.summary}")
        lines.append("")

    lines.append("【证据记录】")
    for ev in evidence_items:
        lines.append(f"- [{ev.source}] {ev.content[:80]}")
    lines.append("")

    lines.append("=" * 50)
    lines.append("本报告由AI生成，仅供参考，不构成投资建议。")
    lines.append("=" * 50)

    answer_text = "\n".join(lines)
    final = FinalAnswer(answer=answer_text, confidence=0.7 if composite else 0.3)

    log_node_end("final_answer_node", {"answer_length": len(answer_text)})
    return {"final_answer": final, "status": AgentStatus.ANSWERED}


def failure_node(state: AgentState) -> dict:
    """Handle failure states."""
    log_node_start("failure_node")
    error_msg = state.get("error_message") or "Agent execution failed"
    log_error("failure_node", RuntimeError(error_msg))
    log_node_end("failure_node")
    return {"error_message": error_msg, "status": AgentStatus.FAILED}
