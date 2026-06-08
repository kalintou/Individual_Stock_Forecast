"""
OpenAI-compatible API planner implementation.

This planner uses any OpenAI-compatible API endpoint for LLM text generation.
It provides a simple generate() interface used by all graph nodes.
"""

import os
from pathlib import Path

from planner.base import BasePlanner
from core.errors import PlannerError


class OpenAICompatiblePlanner(BasePlanner):
    """
    Planner that uses any OpenAI-compatible API for reasoning.

    Supports providers like OpenAI, DashScope, xi-ai.cn, etc.

    Args:
        model: Model name (default: "gpt-4o")
        api_key: API key. If None, reads from environment variable.
        base_url: API base URL
        max_retries: Number of retries on API failure
    """

    def __init__(
        self,
        model: str = "gpt-4o",
        api_key: str | None = None,
        base_url: str = "https://api-2.xi-ai.cn/v1",
        max_retries: int = 3,
    ) -> None:
        self._model = model
        self._api_key = api_key or os.getenv("OPENAI_API_KEY") or os.getenv("DASHSCOPE_API_KEY")
        self._base_url = base_url
        self._max_retries = max_retries

        if not self._api_key:
            raise PlannerError(
                "No API key provided. Set OPENAI_API_KEY or DASHSCOPE_API_KEY env var, "
                "or pass api_key explicitly.",
            )

        try:
            from openai import OpenAI
        except ImportError:
            raise PlannerError("openai package not installed. Run: pip install openai")

        self._client = OpenAI(api_key=self._api_key, base_url=self._base_url, timeout=60.0)

    @property
    def name(self) -> str:
        return f"openai_compatible_planner_{self._model}"

    def generate(self, system_prompt: str, user_prompt: str) -> str:
        """Generic LLM text generation with the planner's API config."""
        return self._call_api(system_prompt, user_prompt)

    # =====================================================================
    # Private helpers
    # =====================================================================

    def _call_api(self, system_prompt: str, user_prompt: str) -> str:
        """Call OpenAI-compatible API and return text response."""
        from openai import APIError, APIConnectionError, RateLimitError

        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ]

        last_error = None
        for attempt in range(self._max_retries):
            try:
                response = self._client.chat.completions.create(
                    model=self._model,
                    messages=messages,
                    max_tokens=2048,
                    temperature=0.3,
                )
                return response.choices[0].message.content or ""
            except (APIError, APIConnectionError, RateLimitError) as e:
                last_error = e
                import time
                time.sleep(0.5 * (2 ** attempt))
                continue

        raise PlannerError(
            f"API call failed after {self._max_retries} retries: {last_error}",
            details={"model": self._model},
        )
