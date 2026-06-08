"""Pydantic request/response schemas for the FastAPI bridge."""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

FactorKey = Literal["technical", "fundamental", "capital", "sentiment"]
ALLOWED_FACTORS: tuple[str, ...] = ("technical", "fundamental", "capital", "sentiment")


class AnalyzeRequest(BaseModel):
    """Request body for POST /api/analyze."""

    query: str = Field(..., min_length=1, description="股票代码、股票名称或自然语言分析问题")
    selected_factors: list[FactorKey] | None = Field(default=None)
    prompt_append: dict[str, str] = Field(default_factory=dict)
    trace: bool = True

    model_config = ConfigDict(extra="forbid")

    @field_validator("query")
    @classmethod
    def validate_query(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("query 不能为空")
        return value

    @field_validator("selected_factors")
    @classmethod
    def validate_selected_factors(cls, value: list[str] | None) -> list[str] | None:
        if value is None:
            return None
        deduped: list[str] = []
        for item in value:
            if item not in ALLOWED_FACTORS:
                raise ValueError(f"不支持的因子: {item}")
            if item not in deduped:
                deduped.append(item)
        if not deduped:
            raise ValueError("请至少选择一个分析因子")
        return deduped

    @field_validator("prompt_append")
    @classmethod
    def sanitize_prompt_append(cls, value: dict[str, str]) -> dict[str, str]:
        allowed_keys = {
            "global",
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
        }
        result: dict[str, str] = {}
        for key, text in (value or {}).items():
            if key in allowed_keys and text is not None:
                result[key] = str(text)
        return result


class HealthResponse(BaseModel):
    ok: bool = True
    service: str = "stock-forecast-agent"
