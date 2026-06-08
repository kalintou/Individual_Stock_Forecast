"""
Technical factor tests for the stock forecast agent.

This file keeps tech-specific tests separate from the existing Phase 2
integration tests.
"""

import importlib.util
import sys
from pathlib import Path


ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))


def _load_nodes_module():
    """Load graph/nodes.py directly to avoid importing graph.builder/langgraph."""
    nodes_path = ROOT / "graph" / "nodes.py"
    spec = importlib.util.spec_from_file_location("nodes_direct", nodes_path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_technical_indicator_calculation():
    """Test expanded technical indicators without requiring akshare/network data."""
    nodes = _load_nodes_module()

    # Tech factor extension test fixture: deterministic 80-day rising series
    # so MA60, 60d return, drawdown, RSI, volume, and breakout fields are populated.
    kline = []
    for i in range(80):
        close = 100 + i
        kline.append({
            "日期": f"2026-01-{(i % 28) + 1:02d}",
            "收盘": close,
            "涨跌幅": 1.0,
            "成交量": 1000 + i * 10,
            "成交额": close * (1000 + i * 10),
        })

    indicators = nodes._calculate_technical_indicators(kline)
    formatted = nodes._format_technical_indicators(indicators)

    assert indicators["MA5"] is not None
    assert indicators["MA20"] is not None
    assert indicators["MA60"] is not None
    assert indicators["return_60d"] is not None
    assert indicators["RSI14"] == 100.0
    assert indicators["is_20d_high"] is True
    assert indicators["is_60d_high"] is True
    assert "Trend:" in formatted
    assert "Breakout:" in formatted


if __name__ == "__main__":
    test_technical_indicator_calculation()
    print("TECHNICAL INDICATOR TEST PASSED")
