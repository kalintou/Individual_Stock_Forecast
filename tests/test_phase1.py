"""
Phase 1 Integration Test for Stock Forecast Agent.

Tests the complete flow: intent clarification → market structure → final answer.
Uses a mock planner to avoid requiring a real API key.

Usage:
    conda activate stock-forecast-agent
    python tests/test_phase1.py
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from core.state import create_initial_state
from core.schemas import UserIntent, MarketStructure
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
                "analysis_summary": "贵州茅台是白酒行业绝对龙头，当前市场主线为消费复苏与高股息防御，茅台作为核心资产受到机构抱团。"
            }"""

        if "investment analysis strategy router" in sys_lower:
            return """{
                "sectors": ["technical", "fundamental", "capital", "sentiment"],
                "analysis_focus": "全面分析",
                "skip_reasons": {}
            }"""

        if "technical analysis expert" in sys_lower:
            return """{"factor_name": "technical", "trend_signal": "Bullish", "score": 75, "key_findings": ["技术面偏多"], "risk_flags": []}"""

        if "fundamental analysis expert" in sys_lower:
            return """{"factor_name": "fundamental", "trend_signal": "Bullish", "score": 80, "key_findings": ["基本面稳健"], "risk_flags": []}"""

        if "capital flow analysis expert" in sys_lower:
            return """{"factor_name": "capital", "trend_signal": "Bullish", "score": 70, "key_findings": ["资金流入"], "risk_flags": []}"""

        if "sentiment analysis expert" in sys_lower:
            return """{"factor_name": "sentiment", "trend_signal": "Neutral", "score": 55, "key_findings": ["情绪中性"], "risk_flags": []}"""

        if "comprehensive investment assessment expert" in sys_lower:
            return """{"composite_score": 70, "trend_direction": "震荡偏多", "position_status": "中位偏强", "risk_level": "中", "summary": "综合评估通过"}"""

        return "{}"


def test_phase1_full_flow():
    """Test the complete Phase 1 graph flow."""
    print("\n" + "=" * 60)
    print("PHASE 1 INTEGRATION TEST")
    print("=" * 60)

    # Create mock planner
    planner = MockPlanner()

    # Build graph
    graph = build_agent_graph(planner=planner)
    print("\n[1/4] Graph built successfully")

    # Create initial state
    state = create_initial_state(query="帮我看看贵州茅台怎么样")
    print(f"[2/4] Initial state created: query='{state['query']}'")

    # Run graph
    final_state = graph.invoke(state)
    print(f"[3/4] Graph execution complete: status={final_state.get('status')}")

    # Verify results
    print("\n[4/4] Verifying results...")

    user_intent = final_state.get("user_intent")
    assert user_intent is not None, "user_intent should be set"
    assert user_intent.stock_name == "贵州茅台", f"Expected 贵州茅台, got {user_intent.stock_name}"
    assert user_intent.stock_code == "600519", f"Expected 600519, got {user_intent.stock_code}"
    print(f"  OK Intent: {user_intent.stock_name} ({user_intent.stock_code})")
    print(f"  OK Intent type: {user_intent.intent_type}")
    print(f"  OK Time horizon: {user_intent.time_horizon}")

    market_structure = final_state.get("market_structure")
    assert market_structure is not None, "market_structure should be set"
    assert market_structure.theme_position == "龙头", f"Expected 龙头, got {market_structure.theme_position}"
    print(f"  OK Market position: {market_structure.theme_position}")
    print(f"  OK Themes: {market_structure.stock_themes}")

    evidence_log = final_state.get("evidence_log", [])
    assert len(evidence_log) > 0, "evidence_log should have entries"
    print(f"  OK Evidence items: {len(evidence_log)}")

    final_answer = final_state.get("final_answer")
    assert final_answer is not None, "final_answer should be set"
    assert "贵州茅台" in final_answer.answer, "Final answer should mention the stock"
    print(f"  OK Final answer length: {len(final_answer.answer)} chars")

    print("\n" + "=" * 60)
    print("ALL PHASE 1 TESTS PASSED OK")
    print("=" * 60)
    print("\nFinal report preview:")
    print("-" * 40)
    print(final_answer.answer[:800])
    print("-" * 40)

    return True


def test_akshare_data_fetching():
    """Test that akshare data fetching works correctly."""
    print("\n" + "=" * 60)
    print("AKSHARE DATA FETCHING TEST")
    print("=" * 60)

    from graph.nodes import (
        _resolve_stock_code,
        _fetch_stock_basic,
        _fetch_recent_kline,
        _fetch_hot_concepts,
    )

    # Test name resolution
    code = _resolve_stock_code("贵州茅台")
    assert code == "600519", f"Expected 600519, got {code}"
    print(f"  OK Name resolution: 贵州茅台 → {code}")

    # Test basic info
    basic = _fetch_stock_basic(code)
    assert basic.get("股票简称") == "贵州茅台", f"Expected 贵州茅台, got {basic.get('股票简称')}"
    assert "白酒" in basic.get("行业", ""), f"Expected 白酒 in industry, got {basic.get('行业')}"
    print(f"  OK Basic info: {basic.get('股票简称')} / {basic.get('行业')}")

    # Test K-line
    kline = _fetch_recent_kline(code, days=5)
    assert len(kline) > 0, "K-line data should not be empty"
    print(f"  OK K-line: {len(kline)} days fetched")
    print(f"    Latest: 收盘={kline[-1]['收盘']}, 涨跌幅={kline[-1]['涨跌幅']}%")

    # Test hot concepts (clist/get endpoint may be blocked server-side)
    concepts = _fetch_hot_concepts(top_n=5)
    if len(concepts) > 0:
        print(f"  OK Hot concepts: {len(concepts)} fetched")
        for c in concepts[:3]:
            print(f"    - {c['板块名称']}: {c['涨跌幅']}%")
    else:
        print(f"  WARN Hot concepts: Eastmoney clist/get endpoint restricted (empty is acceptable)")

    print("\nAKSHARE TESTS PASSED OK")
    return True


if __name__ == "__main__":
    try:
        test_akshare_data_fetching()
        test_phase1_full_flow()
    except AssertionError as e:
        print(f"\nTEST FAILED: {e}")
        sys.exit(1)
    except Exception as e:
        print(f"\nTEST ERROR: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
