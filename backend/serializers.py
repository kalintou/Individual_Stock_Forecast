"""Serialization helpers for API-safe JSON responses."""

from __future__ import annotations

from datetime import date, datetime
from enum import Enum
from typing import Any

from pydantic import BaseModel

FACTOR_LABELS = {
    "technical": "技术面",
    "fundamental": "基本面",
    "capital": "资金面",
    "sentiment": "情绪面",
}

NODE_LABELS = {
    "intent_clarification_node": "解析用户意图",
    "market_structure_node": "市场结构定位",
    "sector_router_node": "因子路由",
    "technical_analysis_node": "技术面分析",
    "fundamental_analysis_node": "基本面分析",
    "capital_analysis_node": "资金面分析",
    "sentiment_analysis_node": "情绪面分析",
    "cross_sector_fusion_node": "综合融合",
    "final_answer_node": "生成最终报告",
    "failure_node": "失败处理",
}

TRACE_NODE_ORDER = [
    "intent_clarification_node",
    "market_structure_node",
    "sector_router_node",
    "technical_analysis_node",
    "fundamental_analysis_node",
    "capital_analysis_node",
    "sentiment_analysis_node",
    "cross_sector_fusion_node",
    "final_answer_node",
    "failure_node",
]



def to_jsonable(obj: Any) -> Any:
    """Convert Pydantic models, datetimes, enums and nested containers to JSONable data."""
    if obj is None:
        return None
    if isinstance(obj, BaseModel):
        return to_jsonable(obj.model_dump())
    if isinstance(obj, Enum):
        return obj.value
    if isinstance(obj, (datetime, date)):
        return obj.isoformat()
    if isinstance(obj, dict):
        return {str(key): to_jsonable(value) for key, value in obj.items()}
    if isinstance(obj, (list, tuple, set)):
        return [to_jsonable(item) for item in obj]
    return obj


def _compact_text(text: Any, max_len: int = 120) -> str:
    if text is None:
        return ""
    s = str(text).replace("\n", " ").strip()
    return s if len(s) <= max_len else s[: max_len - 1] + "…"


def _summarize_output(output: dict[str, Any]) -> str:
    """Create a short user-safe trace summary from a node output update."""
    if not isinstance(output, dict):
        return _compact_text(output)

    if output.get("error_message"):
        return f"执行失败：{_compact_text(output.get('error_message'))}"

    if output.get("user_intent"):
        intent = output["user_intent"]
        return f"识别到 {intent.get('stock_name', '')}（{intent.get('stock_code', '')}），周期：{intent.get('time_horizon', '未知')}"

    if output.get("market_structure"):
        market = output["market_structure"]
        return _compact_text(market.get("analysis_summary") or market.get("theme_position") or "市场结构完成")

    if output.get("sector_route"):
        route = output["sector_route"]
        sectors = route.get("sectors", [])
        labels = [FACTOR_LABELS.get(key, key) for key in sectors]
        return "本次执行因子：" + "、".join(labels)

    for key in ("technical_evidence", "fundamental_evidence", "capital_evidence", "sentiment_evidence"):
        evidence = output.get(key)
        if evidence:
            factor = key.replace("_evidence", "")
            return f"{FACTOR_LABELS.get(factor, factor)}完成：评分 {evidence.get('score', 'N/A')}，信号 {evidence.get('trend_signal', '未知')}"
        if key in output and output.get(key) is None:
            factor = key.replace("_evidence", "")
            return f"{FACTOR_LABELS.get(factor, factor)}未选择，本次跳过"

    if output.get("composite_assessment"):
        assessment = output["composite_assessment"]
        return f"综合评分 {assessment.get('composite_score', 'N/A')}，风险等级 {assessment.get('risk_level', '未知')}"

    if output.get("final_answer"):
        final = output["final_answer"]
        return f"最终报告生成完成，置信度 {final.get('confidence', 'N/A')}"

    if output.get("status"):
        return f"状态：{output.get('status')}"

    return "节点执行完成"


def sanitize_trace(raw_trace: list[dict[str, Any]] | None) -> list[dict[str, Any]]:
    """Expose execution trace only, never full prompts, API keys, or private chain-of-thought.

    The graph is a fixed DAG, so each logical node should appear at most once in
    the UI. We still defensively de-duplicate by node name and keep the latest
    entry, then return rows in graph order. This prevents any accidental retry or
    stale trace row from showing duplicate factor analyses to the user.
    """
    latest_by_node: dict[str, dict[str, Any]] = {}
    unknown_rows: list[dict[str, Any]] = []

    for entry in raw_trace or []:
        output = to_jsonable(entry.get("output", {}))
        node = str(entry.get("node", ""))
        row = {
            "node": node,
            "node_label": NODE_LABELS.get(node, node or "未知节点"),
            "elapsed_ms": entry.get("elapsed_ms"),
            "timestamp": entry.get("timestamp"),
            "status": "完成" if not (isinstance(output, dict) and output.get("error_message")) else "失败",
            "output_summary": _summarize_output(output if isinstance(output, dict) else {}),
        }
        if node in TRACE_NODE_ORDER:
            latest_by_node[node] = row
        else:
            unknown_rows.append(row)

    safe = [latest_by_node[node] for node in TRACE_NODE_ORDER if node in latest_by_node]
    safe.extend(unknown_rows)
    return safe


def _factor_scores(factors: dict[str, Any]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for key, evidence in factors.items():
        if evidence and isinstance(evidence, dict):
            rows.append({"factor": key, "label": FACTOR_LABELS.get(key, key), "score": evidence.get("score", 0)})
    return rows


def build_analyze_response(final_state: dict[str, Any]) -> dict[str, Any]:
    """Normalize LangGraph final state into the API response contract."""
    state = to_jsonable(final_state or {})
    factors = {
        "technical": state.get("technical_evidence"),
        "fundamental": state.get("fundamental_evidence"),
        "capital": state.get("capital_evidence"),
        "sentiment": state.get("sentiment_evidence"),
    }

    response = {
        "status": state.get("status", "failed"),
        "user_intent": state.get("user_intent"),
        "market_structure": state.get("market_structure"),
        "sector_route": state.get("sector_route"),
        "factors": factors,
        "composite_assessment": state.get("composite_assessment"),
        "final_answer": state.get("final_answer"),
        "evidence_log": state.get("evidence_log", []),
        "trace": sanitize_trace(state.get("trace", [])),
        "charts": {
            "factor_scores": _factor_scores(factors),
            "kline": [],
            "capital_flow": [],
            "hot_stocks": [],
        },
        "error_message": state.get("error_message"),
    }
    return response
