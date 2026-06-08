"""
Phase 2 Integration Test for Stock Forecast Agent.

Tests the complete flow including:
    intent -> market_structure -> sector_router -> 4 factor nodes
    -> cross_sector_fusion -> final_answer

Uses a mock planner to avoid requiring a real API key.

Usage:
    conda activate stock-fundamental-agent   # 或你本地的课程环境
    pip install -r requirements.txt          # 含 akshare，便于拉取真实数据
    python tests/test_phase2.py
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from core.state import create_initial_state
from core.schemas import UserIntent, MarketStructure, SectorRoute, FactorEvidence, CompositeAssessment
from core.constants import AgentStatus
from planner.base import BasePlanner
from graph.builder import build_agent_graph


class MockPlanner(BasePlanner):
    """Mock planner for testing without API calls."""

    @property
    def name(self) -> str:
        return "mock_planner"

    def generate(self, system_prompt: str, user_prompt: str) -> str:
        """Return canned responses based on prompt content."""
        sys_lower = system_prompt.lower()

        # Use system prompt for precise matching — each system prompt has a unique identity phrase
        if "intent parsing expert" in sys_lower:
            return """{
                "stock_name": "贵州茅台",
                "stock_code": "600519",
                "intent_type": "analysis",
                "time_horizon": "medium",
                "risk_preference": "moderate",
                "clarified_query": "全面分析贵州茅台的投资价值"
            }"""

        if "market structure analyst for chinese a-shares" in sys_lower:
            return """{
                "current_market_themes": ["消费复苏", "高股息防御"],
                "stock_themes": ["白酒", "消费复苏"],
                "theme_position": "龙头",
                "market_sentiment": "防御性偏好，资金抱团核心资产",
                "sector_heat_rank": 5,
                "analysis_summary": "贵州茅台是白酒行业绝对龙头，当前市场主线为消费复苏与高股息防御。"
            }"""

        if "investment analysis strategy router" in sys_lower:
            return """{
                "sectors": ["technical", "fundamental", "capital", "sentiment"],
                "analysis_focus": "全面分析茅台的技术面、基本面、资金面和情绪面",
                "skip_reasons": {}
            }"""

        if "technical analysis expert" in sys_lower:
            return """{
                "factor_name": "technical",
                "trend_signal": "Bullish",
                "score": 75,
                "key_findings": ["股价在MA20上方运行", "MACD金叉", "成交量温和放大"],
                "risk_flags": [],
                "raw_data_summary": "技术面偏多，趋势向上"
            }"""

        if "fundamental analysis expert" in sys_lower:
            return """{
                "factor_name": "fundamental",
                "trend_signal": "Bullish",
                "score": 80,
                "key_findings": ["PE-TTM处于历史中位数", "ROE维持高位", "现金流充裕"],
                "risk_flags": [],
                "raw_data_summary": "基本面稳健，估值合理"
            }"""

        if "capital flow analysis expert" in sys_lower:
            return """{
                "factor_name": "capital",
                "trend_signal": "Bullish",
                "score": 70,
                "key_findings": ["主力资金连续3日净流入", "北向资金增持"],
                "risk_flags": ["短期游资占比上升"],
                "raw_data_summary": "资金面偏多，但需警惕游资扰动"
            }"""

        if "sentiment analysis expert" in sys_lower:
            return """{
                "factor_name": "sentiment",
                "trend_signal": "Neutral",
                "score": 55,
                "key_findings": ["茅台新品发布引发关注", "机构研报覆盖密集"],
                "risk_flags": ["市场对白酒消费复苏预期存在分歧"],
                "raw_data_summary": "情绪面中性，多空交织"
            }"""

        if "comprehensive investment assessment expert for chinese a-shares" in sys_lower:
            return """{
                "composite_score": 70,
                "trend_direction": "震荡偏多",
                "position_status": "中位偏强",
                "risk_level": "中",
                "risk_details": ["短期游资占比上升", "市场对消费复苏预期分歧"],
                "summary": "综合评估：茅台当前处于震荡偏多格局，基本面和技术面支撑较强，资金面积极但情绪面中性。建议关注回调买入机会。"
            }"""

        # Fallback for edge cases
        combined = (system_prompt + user_prompt).lower()
        if "intent" in combined and "parse" in combined:
            return """{"stock_name": "贵州茅台", "stock_code": "600519", "intent_type": "analysis", "time_horizon": "medium", "risk_preference": "moderate", "clarified_query": "全面分析贵州茅台的投资价值"}"""

        return "{}"


def test_fundamental_metric_calculation_complete_data():
    """Test financial statement based fundamental metric calculation."""
    from graph.nodes import _calculate_fundamental_metrics

    reports = {
        "current": {
            "营业收入": 1000.0,
            "营业成本": 600.0,
            "净利润": 180.0,
            "归母净利润": 160.0,
            "总资产": 3000.0,
            "总负债": 1200.0,
            "归母净资产": 1500.0,
            "经营现金流净额": 220.0,
        },
        "previous": {
            "营业收入": 800.0,
            "净利润": 120.0,
            "归母净资产": 1300.0,
        },
    }
    valuation = {"总市值": 3200.0, "PE_DYNAMIC": 21.0, "PB": 2.2}
    basic = {"行业": "测试行业"}

    metrics = _calculate_fundamental_metrics(reports, valuation, basic)

    assert metrics["industry"] == "测试行业"
    assert metrics["pe"] == 20.0
    assert round(metrics["pb"], 4) == 2.1333
    assert round(metrics["roe"], 4) == 0.1143
    assert metrics["gross_margin"] == 0.4
    assert metrics["net_margin"] == 0.18
    assert metrics["revenue_yoy"] == 0.25
    assert metrics["net_profit_yoy"] == 0.5
    assert metrics["debt_to_asset"] == 0.4
    assert round(metrics["ocf_to_net_profit"], 4) == 1.2222
    assert metrics["missing_fields"] == []


def test_fundamental_metric_calculation_missing_data_uses_fallbacks():
    """Test missing statement fields do not crash and valuation fallbacks remain available."""
    from graph.nodes import _calculate_fundamental_metrics

    reports = {
        "current": {
            "营业收入": 0.0,
            "营业成本": None,
            "净利润": None,
            "归母净利润": None,
            "总资产": None,
            "总负债": None,
            "归母净资产": None,
            "经营现金流净额": None,
        },
        "previous": {},
    }
    valuation = {"总市值": 3200.0, "PE_DYNAMIC": 21.0, "PB": 2.2}
    basic = {"行业": "测试行业"}

    metrics = _calculate_fundamental_metrics(reports, valuation, basic)

    assert metrics["pe"] == 21.0
    assert metrics["pb"] == 2.2
    assert metrics["roe"] is None
    assert metrics["gross_margin"] is None
    assert metrics["net_margin"] is None
    assert metrics["revenue_yoy"] is None
    assert metrics["net_profit_yoy"] is None
    assert metrics["debt_to_asset"] is None
    assert metrics["ocf_to_net_profit"] is None
    assert "ROE" in metrics["missing_fields"]
    assert "毛利率" in metrics["missing_fields"]
    assert "净利率" in metrics["missing_fields"]
    assert "营收同比" in metrics["missing_fields"]
    assert "净利润同比" in metrics["missing_fields"]
    assert "资产负债率" in metrics["missing_fields"]
    assert "经营现金流/净利润" in metrics["missing_fields"]


def test_fundamental_metric_formatting_sections():
    """Test LLM prompt text contains all required fundamental sections."""
    from graph.nodes import _format_fundamental_metrics

    metrics = {
        "industry": "测试行业",
        "pe": 20.0,
        "pb": 2.13,
        "roe": 0.1143,
        "gross_margin": 0.4,
        "net_margin": 0.18,
        "revenue_yoy": 0.25,
        "net_profit_yoy": 0.5,
        "debt_to_asset": 0.4,
        "ocf_to_net_profit": 1.2222,
        "score_hint": 75,
        "missing_fields": [],
        "data_sources": ["利润表", "资产负债表", "现金流量表", "行情数据"],
    }

    text = _format_fundamental_metrics(metrics)

    assert "【估值】" in text
    assert "PE: 20.00" in text
    assert "PB: 2.13" in text
    assert "【盈利能力】" in text
    assert "ROE: 11.43%" in text
    assert "毛利率: 40.00%" in text
    assert "净利率: 18.00%" in text
    assert "【成长性】" in text
    assert "营收同比: 25.00%" in text
    assert "净利润同比: 50.00%" in text
    assert "【财务安全】" in text
    assert "资产负债率: 40.00%" in text
    assert "【现金流质量】" in text
    assert "经营现金流/净利润: 1.22" in text
    assert "【数据质量】" in text
    assert "缺失字段: 无" in text
    assert "Python预评分: 75/100" in text


def test_fundamental_report_fetch_shape():
    """Test financial report fetch helper returns the expected stable shape."""
    from graph.nodes import _fetch_financial_reports

    reports = _fetch_financial_reports("600519")

    assert "current" in reports
    assert "previous" in reports
    assert "data_sources" in reports
    assert isinstance(reports["current"], dict)
    assert isinstance(reports["previous"], dict)
    assert isinstance(reports["data_sources"], list)


def test_fundamental_node_uses_structured_metric_prompt():
    """Test fundamental node sends grouped structured metrics to the planner."""
    from graph.nodes import fundamental_analysis_node

    class CapturingPlanner(MockPlanner):
        def __init__(self):
            self.user_prompt = ""

        def generate(self, system_prompt: str, user_prompt: str) -> str:
            self.user_prompt = user_prompt
            return """{
                "factor_name": "fundamental",
                "trend_signal": "Neutral",
                "score": 60,
                "key_findings": ["基本面指标已结构化"],
                "risk_flags": [],
                "raw_data_summary": "已读取基本面结构化数据"
            }"""

    state = create_initial_state(query="分析贵州茅台")
    state["user_intent"] = UserIntent(stock_name="贵州茅台", stock_code="600519")
    state["sector_route"] = SectorRoute(sectors=["fundamental"], analysis_focus="基本面分析")
    planner = CapturingPlanner()

    result = fundamental_analysis_node(state, planner)

    evidence = result["fundamental_evidence"]
    assert evidence.factor_name == "fundamental"
    assert evidence.score == 60
    assert "【估值】" in planner.user_prompt
    assert "【盈利能力】" in planner.user_prompt
    assert "【成长性】" in planner.user_prompt
    assert "【财务安全】" in planner.user_prompt
    assert "【现金流质量】" in planner.user_prompt
    assert "【数据质量】" in planner.user_prompt


def test_phase2_full_flow():
    """Test the complete Phase 2 graph flow."""
    print("\n" + "=" * 60)
    print("PHASE 2 INTEGRATION TEST")
    print("=" * 60)

    planner = MockPlanner()
    graph = build_agent_graph(planner=planner)
    print("\n[1/5] Graph built successfully (Phase 2)")

    state = create_initial_state(query="帮我看看贵州茅台怎么样")
    print(f"[2/5] Initial state created: query='{state['query']}'")

    final_state = graph.invoke(state)
    print(f"[3/5] Graph execution complete: status={final_state.get('status')}")

    print("\n[4/5] Verifying Phase 1 fields...")

    user_intent = final_state.get("user_intent")
    assert user_intent is not None, "user_intent should be set"
    assert user_intent.stock_name == "贵州茅台"
    assert user_intent.stock_code == "600519"
    print(f"  OK Intent: {user_intent.stock_name} ({user_intent.stock_code})")

    market_structure = final_state.get("market_structure")
    assert market_structure is not None, "market_structure should be set"
    assert market_structure.theme_position == "龙头"
    print(f"  OK Market position: {market_structure.theme_position}")

    print("\n[5/5] Verifying Phase 2 fields...")

    sector_route = final_state.get("sector_route")
    assert sector_route is not None, "sector_route should be set"
    assert "technical" in sector_route.sectors
    assert "fundamental" in sector_route.sectors
    print(f"  OK Sector route: {sector_route.sectors}")
    print(f"  OK Analysis focus: {sector_route.analysis_focus}")

    tech = final_state.get("technical_evidence")
    assert tech is not None, "technical_evidence should be set"
    assert tech.factor_name == "technical"
    assert tech.score == 75
    print(f"  OK Technical: {tech.trend_signal} (score={tech.score})")

    fund = final_state.get("fundamental_evidence")
    assert fund is not None, "fundamental_evidence should be set"
    assert fund.factor_name == "fundamental"
    assert fund.score == 80
    print(f"  OK Fundamental: {fund.trend_signal} (score={fund.score})")

    cap = final_state.get("capital_evidence")
    assert cap is not None, "capital_evidence should be set"
    assert cap.factor_name == "capital"
    assert cap.score == 70
    print(f"  OK Capital: {cap.trend_signal} (score={cap.score})")

    sent = final_state.get("sentiment_evidence")
    assert sent is not None, "sentiment_evidence should be set"
    assert sent.factor_name == "sentiment"
    assert sent.score == 55
    print(f"  OK Sentiment: {sent.trend_signal} (score={sent.score})")

    composite = final_state.get("composite_assessment")
    assert composite is not None, "composite_assessment should be set"
    assert composite.composite_score == 70
    assert composite.trend_direction == "震荡偏多"
    print(f"  OK Composite: {composite.trend_direction} (score={composite.composite_score})")
    print(f"  OK Risk level: {composite.risk_level}")

    evidence_log = final_state.get("evidence_log", [])
    assert len(evidence_log) >= 4, f"Expected >=4 evidence items, got {len(evidence_log)}"
    print(f"  OK Evidence items: {len(evidence_log)}")

    final_answer = final_state.get("final_answer")
    assert final_answer is not None, "final_answer should be set"
    assert "贵州茅台" in final_answer.answer
    assert "技术面" in final_answer.answer
    assert "综合评估" in final_answer.answer
    print(f"  OK Final answer length: {len(final_answer.answer)} chars")

    print("\n" + "=" * 60)
    print("ALL PHASE 2 TESTS PASSED OK")
    print("=" * 60)
    print("\nFinal report preview:")
    print("-" * 40)
    print(final_answer.answer[:1000])
    print("-" * 40)

    return True


def test_sector_routing_skip():
    """Test that skipped sectors produce None evidence."""
    print("\n" + "=" * 60)
    print("SECTOR ROUTING SKIP TEST")
    print("=" * 60)

    class SkipPlanner(MockPlanner):
        def generate(self, system_prompt: str, user_prompt: str) -> str:
            sys_lower = system_prompt.lower()
            if "strategy router" in sys_lower or "which factor sectors" in sys_lower:
                return """{
                    "sectors": ["technical", "sentiment"],
                    "analysis_focus": "只分析技术面和情绪面",
                    "skip_reasons": {
                        "fundamental": "用户是短线交易者，基本面不敏感",
                        "capital": "用户意图已包含对资金的判断"
                    }
                }"""
            return super().generate(system_prompt, user_prompt)

    planner = SkipPlanner()
    graph = build_agent_graph(planner=planner)
    state = create_initial_state(query="明天茅台能买吗")
    final_state = graph.invoke(state)

    assert final_state.get("technical_evidence") is not None
    assert final_state.get("sentiment_evidence") is not None
    assert final_state.get("fundamental_evidence") is None
    assert final_state.get("capital_evidence") is None

    print("  OK Technical: analyzed")
    print("  OK Sentiment: analyzed")
    print("  OK Fundamental: skipped (None)")
    print("  OK Capital: skipped (None)")

    composite = final_state.get("composite_assessment")
    assert composite is not None
    print(f"  OK Composite still computed with 2 factors (score={composite.composite_score})")

    print("\nSECTOR SKIP TEST PASSED OK")
    return True


def test_akshare_phase2_data():
    """Test Phase 2 specific data fetching."""
    print("\n" + "=" * 60)
    print("PHASE 2 DATA FETCHING TEST")
    print("=" * 60)

    from graph.nodes import (
        _fetch_valuation,
        _fetch_capital_flow,
        _fetch_news,
        _calculate_ma,
        _fetch_recent_kline,
    )

    code = "600519"

    valuation = _fetch_valuation(code)
    print(f"  Valuation: {valuation}")

    flow = _fetch_capital_flow(code, days=3)
    print(f"  Capital flow records: {len(flow)}")
    for f in flow[:2]:
        print(f"    {f}")

    news = _fetch_news(code, top_n=3)
    print(f"  News records: {len(news)}")
    for n in news[:2]:
        print(f"    [{n.get('发布时间', 'N/A')}] {n.get('新闻标题', 'N/A')[:40]}...")

    kline = _fetch_recent_kline(code, days=20)
    ma = _calculate_ma(kline)
    print(f"  MA calculation: {ma}")

    print("\nPHASE 2 DATA TEST COMPLETE")
    return True


if __name__ == "__main__":
    try:
        test_fundamental_metric_calculation_complete_data()
        test_fundamental_metric_calculation_missing_data_uses_fallbacks()
        test_fundamental_metric_formatting_sections()
        test_fundamental_report_fetch_shape()
        test_fundamental_node_uses_structured_metric_prompt()
        test_akshare_phase2_data()
        test_phase2_full_flow()
        test_sector_routing_skip()
    except AssertionError as e:
        print(f"\nTEST FAILED: {e}")
        sys.exit(1)
    except Exception as e:
        print(f"\nTEST ERROR: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
