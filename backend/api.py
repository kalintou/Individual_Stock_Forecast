"""FastAPI app that bridges the Next.js frontend to the Python LangGraph workflow."""

from __future__ import annotations

import json
import sys
import threading
import time
import uuid
from pathlib import Path
from typing import Any, Generator

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from backend.market_data import debug_hot_stocks, fetch_chart_data, fetch_hot_stocks
from backend.schemas import ALLOWED_FACTORS, AnalyzeRequest, HealthResponse
from backend.serializers import build_analyze_response, sanitize_trace, to_jsonable
from graph.trace import clear_trace, drop_trace, get_trace_entries
from main import run_agent_for_api

app = FastAPI(title="个股智能分析系统 API", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000", "http://127.0.0.1:3000"],
    allow_origin_regex=r"https://.*\.vercel\.app",
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)


def _selected_factors(req: AnalyzeRequest) -> list[str]:
    return list(req.selected_factors or list(ALLOWED_FACTORS))


def _attach_chart_payload(response: dict[str, Any]) -> dict[str, Any]:
    """Attach chart and hot-stock data without breaking the core answer if market data fails."""
    charts = response.setdefault("charts", {})
    stock_code = (response.get("user_intent") or {}).get("stock_code")
    if stock_code:
        try:
            chart_data = fetch_chart_data(stock_code)
            charts["kline"] = chart_data.get("kline", [])
        except Exception:
            charts["kline"] = []
    try:
        charts["hot_stocks"] = fetch_hot_stocks(top_n=10)
    except Exception:
        charts["hot_stocks"] = []
    return response


def _sse(event: str, data: Any) -> str:
    payload = json.dumps(to_jsonable(data), ensure_ascii=False, default=str)
    return f"event: {event}\ndata: {payload}\n\n"


@app.get("/api/health", response_model=HealthResponse)
def health() -> HealthResponse:
    return HealthResponse()


@app.post("/api/analyze")
def analyze(req: AnalyzeRequest) -> dict:
    selected = _selected_factors(req)
    try:
        trace_run_id = str(uuid.uuid4()) if req.trace else None
        final_state = run_agent_for_api(
            query=req.query,
            selected_factors=selected,
            prompt_append=req.prompt_append,
            trace=req.trace,
            trace_run_id=trace_run_id,
        )
        response = build_analyze_response(final_state)
        payload = to_jsonable(_attach_chart_payload(response))
        if trace_run_id:
            drop_trace(trace_run_id)
        return payload
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"分析接口执行失败: {exc}") from exc


@app.post("/api/analyze/stream")
def analyze_stream(req: AnalyzeRequest) -> StreamingResponse:
    """
    Stream safe execution trace updates via Server-Sent Events.

    Events:
    - started: request accepted
    - trace: latest sanitized trace list after a node finishes
    - final: full AnalyzeResponse when the workflow finishes
    - error: error message if the workflow fails unexpectedly
    """

    def generate() -> Generator[str, None, None]:
        selected = _selected_factors(req)
        trace_run_id = str(uuid.uuid4())
        result_holder: dict[str, Any] = {}
        error_holder: dict[str, str] = {}
        done = threading.Event()

        clear_trace(trace_run_id)
        yield _sse("started", {"status": "running", "message": "分析任务已开始"})

        def worker() -> None:
            try:
                final_state = run_agent_for_api(
                    query=req.query,
                    selected_factors=selected,
                    prompt_append=req.prompt_append,
                    trace=True,
                    trace_run_id=trace_run_id,
                )
                result_holder["state"] = final_state
            except Exception as exc:  # pragma: no cover - defensive streaming guard
                error_holder["message"] = f"分析接口执行失败: {exc}"
            finally:
                done.set()

        thread = threading.Thread(target=worker, daemon=True)
        thread.start()

        emitted_count = 0
        while not done.is_set():
            entries = get_trace_entries(trace_run_id)
            if len(entries) > emitted_count:
                emitted_count = len(entries)
                yield _sse(
                    "trace",
                    {
                        "status": "running",
                        "trace": sanitize_trace(entries),
                    },
                )
            time.sleep(0.25)

        thread.join(timeout=0.1)
        entries = get_trace_entries(trace_run_id)
        if len(entries) > emitted_count:
            yield _sse(
                "trace",
                {
                    "status": "running",
                    "trace": sanitize_trace(entries),
                },
            )

        if error_holder:
            yield _sse("error", {"status": "failed", "error_message": error_holder["message"]})
            drop_trace(trace_run_id)
            return

        final_state = result_holder.get("state") or {}
        response = _attach_chart_payload(build_analyze_response(final_state))
        yield _sse("final", response)
        drop_trace(trace_run_id)

    return StreamingResponse(
        generate(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@app.get("/api/prompts")
def get_prompts() -> dict[str, str]:
    prompt_dir = PROJECT_ROOT / "prompts"
    names = [
        "intent_system",
        "market_structure_system",
        "sector_route_system",
        "technical_system",
        "fundamental_system",
        "capital_system",
        "sentiment_system",
        "sentiment_short_term",
        "sentiment_long_term",
        "fusion_system",
    ]
    result: dict[str, str] = {}
    for name in names:
        path = prompt_dir / f"{name}.md"
        result[name] = path.read_text(encoding="utf-8") if path.exists() else ""
    return result


@app.get("/api/hot-stocks")
def hot_stocks(top_n: int = 30) -> list[dict]:
    top_n = max(1, min(int(top_n or 30), 100))
    return fetch_hot_stocks(top_n=top_n)


@app.get("/api/hot-stocks/debug")
def hot_stocks_debug(top_n: int = 10) -> dict:
    """诊断热门股票名称/涨幅补全是否成功。"""
    top_n = max(1, min(int(top_n or 10), 30))
    return debug_hot_stocks(top_n=top_n)


@app.get("/api/chart-data/{stock_code}")
def chart_data(stock_code: str) -> dict:
    stock_code = stock_code.strip()
    if not stock_code:
        raise HTTPException(status_code=400, detail="stock_code 不能为空")
    return fetch_chart_data(stock_code)
