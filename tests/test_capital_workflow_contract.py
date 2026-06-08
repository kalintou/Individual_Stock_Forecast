# tests/test_capital_workflow_contract.py

import json
from types import SimpleNamespace

import pandas as pd
import pytest


# ============================================================
# Helpers
# ============================================================

class DummyPlanner:
    """
    用于测试 capital_analysis_node 的假 LLM。
    capital_analysis_node 当前会优先调用 planner.invoke(prompt)。
    """

    def invoke(self, prompt: str):
        return json.dumps(
            {
                "key_findings": [
                    "DummyPlanner 测试返回：资金因子解释生成成功。"
                ],
                "risk_flags": [],
                "raw_data_summary": "DummyPlanner 测试返回：资金面解释生成成功。",
            },
            ensure_ascii=False,
        )


def make_fake_flow_df():
    """
    构造一个稳定的资金流 DataFrame，避免测试依赖真实 AkShare 网络。
    """
    return pd.DataFrame(
        {
            "日期": pd.date_range("2026-04-24", periods=5),
            "主力净流入-净额": [
                -100000000,
                -200000000,
                -300000000,
                -400000000,
                -500000000,
            ],
            "主力净流入-净占比": [-1.0, -2.0, -3.0, -4.0, -5.0],
            "超大单净流入-净额": [
                -50000000,
                -100000000,
                -150000000,
                -200000000,
                -250000000,
            ],
            "大单净流入-净额": [
                -50000000,
                -100000000,
                -150000000,
                -200000000,
                -250000000,
            ],
            "中单净流入-净额": [
                100000000,
                200000000,
                300000000,
                400000000,
                500000000,
            ],
            "小单净流入-净额": [
                0,
                0,
                0,
                0,
                0,
            ],
            "涨跌幅": [-0.5, -0.8, -1.0, -1.2, -1.5],
        }
    )


def assert_factor_evidence_contract(evidence):
    """
    验证 capital_evidence 是否满足 workflow 需要的基本格式。
    """
    assert evidence is not None

    assert hasattr(evidence, "factor_name")
    assert hasattr(evidence, "trend_signal")
    assert hasattr(evidence, "score")
    assert hasattr(evidence, "key_findings")
    assert hasattr(evidence, "risk_flags")
    assert hasattr(evidence, "raw_data_summary")

    assert evidence.factor_name == "capital"
    assert evidence.trend_signal in {"Bullish", "Neutral", "Bearish"}
    assert isinstance(evidence.score, int)
    assert 0 <= evidence.score <= 100
    assert isinstance(evidence.key_findings, list)
    assert isinstance(evidence.risk_flags, list)
    assert isinstance(evidence.raw_data_summary, str)


# ============================================================
# 1. 测试 capital_factor.py 本身
# ============================================================

def test_capital_factor_calculation_contract():
    """
    测试 capital_factor.py 是否能完成：

    DataFrame
    -> calculate_capital_indicators
    -> score_capital_factor
    -> build_capital_evidence
    """

    from capital_factor import (
        calculate_capital_indicators,
        score_capital_factor,
        build_capital_evidence,
    )

    flow_df = make_fake_flow_df()

    indicators = calculate_capital_indicators(flow_df)

    assert indicators["data_available"] is True
    assert indicators["data_quality"] == "ok"
    assert "latest_main_net_inflow" in indicators
    assert "main_net_inflow_3d_sum" in indicators
    assert "main_net_inflow_5d_sum" in indicators
    assert "main_net_inflow_5d_mean" in indicators
    assert "main_net_inflow_ratio_5d_mean" in indicators
    assert "consecutive_inflow_days" in indicators
    assert "consecutive_outflow_days" in indicators
    assert "accumulation_signal" in indicators
    assert "retail_chasing_risk" in indicators

    scored = score_capital_factor(indicators)

    assert "score" in scored
    assert "trend_signal" in scored
    assert "key_findings" in scored
    assert "risk_flags" in scored

    assert isinstance(scored["score"], int)
    assert 0 <= scored["score"] <= 100
    assert scored["trend_signal"] in {"Bullish", "Neutral", "Bearish"}

    evidence = build_capital_evidence(
        stock_name="贵州茅台",
        stock_code="600519",
        indicators=indicators,
    )

    assert_factor_evidence_contract(evidence)


def test_resolve_market_contract():
    """
    测试股票代码市场识别。
    """

    from capital_factor import resolve_market

    assert resolve_market("600519") == "sh"
    assert resolve_market("688981") == "sh"
    assert resolve_market("000001") == "sz"
    assert resolve_market("300750") == "sz"
    assert resolve_market("920001") == "bj"
    assert resolve_market("830799") == "bj"


def test_capital_factor_empty_data_fallback():
    """
    测试资金数据为空时，capital_factor.py 能否中性兜底。
    """

    from capital_factor import (
        calculate_capital_indicators,
        score_capital_factor,
        build_capital_evidence,
    )

    indicators = calculate_capital_indicators(pd.DataFrame())
    scored = score_capital_factor(indicators)

    assert scored["score"] == 50
    assert scored["trend_signal"] == "Neutral"
    assert len(scored["risk_flags"]) >= 1

    evidence = build_capital_evidence(
        stock_name="测试股票",
        stock_code="600000",
        indicators=indicators,
    )

    assert_factor_evidence_contract(evidence)
    assert evidence.score == 50
    assert evidence.trend_signal == "Neutral"


# ============================================================
# 2. 测试 capital_analysis_node 是否返回 workflow 需要的信息
# ============================================================

def test_capital_analysis_node_returns_workflow_contract(monkeypatch):
    """
    测试主 workflow 关心的接口：

    capital_analysis_node(state, planner)
    -> {
        "capital_evidence": FactorEvidence,
        "evidence_log": [...]
       }

    这个测试模拟顶层 state["stock_code"] 存在的情况。
    """

    import graph.nodes as nodes

    monkeypatch.setattr(nodes, "fetch_capital_flow", lambda stock_code: make_fake_flow_df())
    monkeypatch.setattr(nodes, "fetch_fund_flow_rank", lambda stock_code, indicator="5日": pd.DataFrame())
    monkeypatch.setattr(nodes, "fetch_margin_data", lambda stock_code: pd.DataFrame())

    state = {
        "stock_code": "600519",
        "stock_name": "贵州茅台",
        "user_intent": "analysis",
        "time_horizon": "medium",
        "market_structure": None,
        "sector_route": SimpleNamespace(
            sectors=["capital"],
            analysis_focus="只测试资金因子",
        ),
    }

    result = nodes.capital_analysis_node(state, DummyPlanner())

    assert isinstance(result, dict)
    assert "capital_evidence" in result
    assert "evidence_log" in result

    evidence = result["capital_evidence"]
    evidence_log = result["evidence_log"]

    assert_factor_evidence_contract(evidence)

    assert isinstance(evidence_log, list)
    assert len(evidence_log) >= 1

    # 这个结果应该来自 DummyPlanner 的解释，但 score/trend_signal 应该来自 capital_factor 规则评分
    assert evidence.factor_name == "capital"
    assert evidence.raw_data_summary


def test_capital_analysis_node_really_calls_capital_factor_functions(monkeypatch):
    """
    测试 capital_analysis_node 是否真的调用了 capital_factor.py 对应函数。

    如果 node 只是自己简单拉数据、直接问 LLM，
    这个测试会失败。
    """

    import graph.nodes as nodes

    calls = {
        "fetch_capital_flow": 0,
        "fetch_fund_flow_rank": 0,
        "fetch_margin_data": 0,
        "calculate_capital_indicators": 0,
        "build_capital_prompt_data": 0,
        "build_capital_evidence": 0,
    }

    original_calculate = nodes.calculate_capital_indicators
    original_prompt_data = nodes.build_capital_prompt_data
    original_build_evidence = nodes.build_capital_evidence

    def fake_fetch_capital_flow(stock_code):
        calls["fetch_capital_flow"] += 1
        return make_fake_flow_df()

    def fake_fetch_fund_flow_rank(stock_code, indicator="5日"):
        calls["fetch_fund_flow_rank"] += 1
        return pd.DataFrame()

    def fake_fetch_margin_data(stock_code):
        calls["fetch_margin_data"] += 1
        return pd.DataFrame()

    def wrapped_calculate_capital_indicators(*args, **kwargs):
        calls["calculate_capital_indicators"] += 1
        return original_calculate(*args, **kwargs)

    def wrapped_build_capital_prompt_data(*args, **kwargs):
        calls["build_capital_prompt_data"] += 1
        return original_prompt_data(*args, **kwargs)

    def wrapped_build_capital_evidence(*args, **kwargs):
        calls["build_capital_evidence"] += 1
        return original_build_evidence(*args, **kwargs)

    monkeypatch.setattr(nodes, "fetch_capital_flow", fake_fetch_capital_flow)
    monkeypatch.setattr(nodes, "fetch_fund_flow_rank", fake_fetch_fund_flow_rank)
    monkeypatch.setattr(nodes, "fetch_margin_data", fake_fetch_margin_data)
    monkeypatch.setattr(nodes, "calculate_capital_indicators", wrapped_calculate_capital_indicators)
    monkeypatch.setattr(nodes, "build_capital_prompt_data", wrapped_build_capital_prompt_data)
    monkeypatch.setattr(nodes, "build_capital_evidence", wrapped_build_capital_evidence)

    state = {
        "stock_code": "600519",
        "stock_name": "贵州茅台",
        "sector_route": SimpleNamespace(
            sectors=["capital"],
            analysis_focus="只测试资金因子",
        ),
    }

    result = nodes.capital_analysis_node(state, DummyPlanner())

    assert "capital_evidence" in result
    assert_factor_evidence_contract(result["capital_evidence"])

    assert calls["fetch_capital_flow"] == 1
    assert calls["fetch_fund_flow_rank"] == 1
    assert calls["fetch_margin_data"] == 1
    assert calls["calculate_capital_indicators"] == 1
    assert calls["build_capital_prompt_data"] == 1
    assert calls["build_capital_evidence"] == 1


# ============================================================
# 3. 测试真实 workflow 状态：股票代码在 user_intent 里
# ============================================================

# @pytest.mark.xfail(
#     reason=(
#         "当前 nodes.py 的 capital_analysis_node 主要读取 state['stock_code']，"
#         "但真实 workflow 中股票代码通常在 state['user_intent'].stock_code。"
#         "修复 capital_analysis_node 的取值逻辑后，可以删除 xfail。"
#     ),
#     strict=False,
# )
def test_capital_analysis_node_accepts_real_workflow_state_user_intent(monkeypatch):
    """
    这个测试模拟真实 workflow 状态：

    intent_clarification_node 返回：
    {
        "user_intent": UserIntent(...)
    }

    因此 capital_analysis_node 应该能从 state["user_intent"].stock_code
    中读取股票代码。

    当前版本如果没有修复，可能返回缺少 stock_code 的兜底结果。
    """

    import graph.nodes as nodes

    monkeypatch.setattr(nodes, "fetch_capital_flow", lambda stock_code: make_fake_flow_df())
    monkeypatch.setattr(nodes, "fetch_fund_flow_rank", lambda stock_code, indicator="5日": pd.DataFrame())
    monkeypatch.setattr(nodes, "fetch_margin_data", lambda stock_code: pd.DataFrame())

    state = {
        "user_intent": SimpleNamespace(
            stock_code="600519",
            stock_name="贵州茅台",
            intent_type="analysis",
            time_horizon="medium",
            risk_preference="medium",
            clarified_query="分析贵州茅台",
        ),
        "market_structure": None,
        "sector_route": SimpleNamespace(
            sectors=["capital"],
            analysis_focus="只测试资金因子",
        ),
    }

    result = nodes.capital_analysis_node(state, DummyPlanner())

    assert "capital_evidence" in result

    evidence = result["capital_evidence"]

    assert_factor_evidence_contract(evidence)

    # 如果正确读取 user_intent.stock_code，就不应该是 UNKNOWN 兜底结果
    assert "UNKNOWN" not in evidence.raw_data_summary
    assert "缺少 stock_code" not in evidence.raw_data_summary


# ============================================================
# 4. 测试缺少股票代码时不会让 workflow 崩溃
# ============================================================

def test_capital_analysis_node_missing_stock_code_fallback():
    """
    如果 state 中完全没有 stock_code，
    capital_analysis_node 应返回 Neutral / 50 兜底结果，
    而不是让 workflow 崩溃。
    """

    import graph.nodes as nodes

    state = {
        "stock_name": "未知股票",
        "sector_route": SimpleNamespace(
            sectors=["capital"],
            analysis_focus="只测试资金因子",
        ),
    }

    result = nodes.capital_analysis_node(state, DummyPlanner())

    assert isinstance(result, dict)
    assert "capital_evidence" in result
    assert "evidence_log" in result

    evidence = result["capital_evidence"]

    assert_factor_evidence_contract(evidence)
    assert evidence.trend_signal == "Neutral"
    assert evidence.score == 50


# ============================================================
# 5. 测试 capital_evidence 能否被 fusion 节点消费
# ============================================================

def test_capital_evidence_can_be_formatted_for_fusion(monkeypatch):
    """
    cross_sector_fusion_node 会通过 _factor_evidence_to_dict(capital_evidence)
    把资金因子证据注入 fusion prompt。

    这里测试 capital_evidence 是否能被正常格式化。
    """

    import graph.nodes as nodes

    monkeypatch.setattr(nodes, "fetch_capital_flow", lambda stock_code: make_fake_flow_df())
    monkeypatch.setattr(nodes, "fetch_fund_flow_rank", lambda stock_code, indicator="5日": pd.DataFrame())
    monkeypatch.setattr(nodes, "fetch_margin_data", lambda stock_code: pd.DataFrame())

    state = {
        "stock_code": "600519",
        "stock_name": "贵州茅台",
        "sector_route": SimpleNamespace(
            sectors=["capital"],
            analysis_focus="只测试资金因子",
        ),
    }

    result = nodes.capital_analysis_node(state, DummyPlanner())
    evidence = result["capital_evidence"]

    formatted = nodes._factor_evidence_to_dict(evidence)

    assert isinstance(formatted, str)
    assert "趋势信号" in formatted
    assert "评分" in formatted
    assert "关键发现" in formatted
    assert "风险标记" in formatted

def test_print_capital_node_output(monkeypatch):
    """
    打印 capital_analysis_node 的输出，方便人工查看。
    运行时使用：
    pytest tests/test_capital_workflow_contract.py::test_print_capital_node_output -q -s
    """

    import graph.nodes as nodes

    monkeypatch.setattr(nodes, "fetch_capital_flow", lambda stock_code: make_fake_flow_df())
    monkeypatch.setattr(nodes, "fetch_fund_flow_rank", lambda stock_code, indicator="5日": pd.DataFrame())
    monkeypatch.setattr(nodes, "fetch_margin_data", lambda stock_code: pd.DataFrame())

    state = {
        "stock_code": "600519",
        "stock_name": "贵州茅台",
        "sector_route": SimpleNamespace(
            sectors=["capital"],
            analysis_focus="只测试资金因子",
        ),
    }

    result = nodes.capital_analysis_node(state, DummyPlanner())
    evidence = result["capital_evidence"]

    print("\n===== Capital Node Output =====")
    print("Return keys:", result.keys())
    print("factor_name:", evidence.factor_name)
    print("trend_signal:", evidence.trend_signal)
    print("score:", evidence.score)
    print("key_findings:", evidence.key_findings)
    print("risk_flags:", evidence.risk_flags)
    print("raw_data_summary:", evidence.raw_data_summary)
    print("evidence_log:", result["evidence_log"])

    assert_factor_evidence_contract(evidence)

@pytest.mark.realdata
def test_real_akshare_capital_factor_output():
    """
    真实 AkShare 数据测试。
    注意：
    这个测试依赖网络和 AkShare 源站，不建议作为默认 CI 测试。
    """

    from capital_factor import analyze_capital_factor

    indicators, evidence = analyze_capital_factor(
        stock_name="贵州茅台",
        stock_code="600519",
        use_rank=True,
        use_margin=True,
    )

    print("\n===== Real AkShare Capital Indicators =====")
    for k, v in indicators.items():
        print(f"{k}: {v}")

    print("\n===== Real AkShare Capital Evidence =====")
    print("factor_name:", evidence.factor_name)
    print("trend_signal:", evidence.trend_signal)
    print("score:", evidence.score)
    print("key_findings:", evidence.key_findings)
    print("risk_flags:", evidence.risk_flags)
    print("raw_data_summary:", evidence.raw_data_summary)

    assert_factor_evidence_contract(evidence)