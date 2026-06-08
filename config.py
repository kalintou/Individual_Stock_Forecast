"""
Configuration management for the stock forecast agent.

Loads settings from:
1. Environment variables (via python-dotenv)
2. Command-line arguments (via argparse)
3. Default fallbacks

Priority: CLI args > .env > defaults
"""

import os
import argparse
from dataclasses import dataclass, field
from pathlib import Path

from dotenv import load_dotenv


def _load_dotenv() -> None:
    """Load .env file if it exists in the project root."""
    env_path = Path(__file__).parent / ".env"
    if env_path.exists():
        load_dotenv(dotenv_path=env_path)


@dataclass
class AgentConfig:
    """
    Complete configuration for running the stock forecast agent.
    """

    # Planner API settings (text reasoning model for all analysis tasks)
    planner_api_key: str = ""
    planner_base_url: str = ""
    planner_model: str = "gpt-4o"

    # Agent behavior
    max_steps: int = 10

    # User query
    query: str = ""

    # Optional
    verbose: bool = False
    trace: bool = False
    trace_dir: str = "."
    extra: dict = field(default_factory=dict)

    @property
    def is_valid(self) -> bool:
        """Check if config has minimum required fields to run."""
        return bool(
            self.planner_api_key
            and self.planner_base_url
            and self.query
        )


def build_parser() -> argparse.ArgumentParser:
    """Build the argument parser for CLI usage."""
    parser = argparse.ArgumentParser(
        description="Stock Forecast Agent: Analyze individual stocks",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Basic analysis
  python main.py --query "帮我看看贵州茅台怎么样" --planner-api-key sk-xxx --planner-base-url https://api.xxx/v1

  # Short-term trade advice
  python main.py --query "明天茅台能买吗" --planner-api-key sk-xxx --planner-base-url https://api.xxx/v1

  # With tracing
  python main.py --query "分析一下宁德时代" --planner-api-key sk-xxx --planner-base-url https://api.xxx/v1 --trace
        """,
    )

    # User query (required)
    parser.add_argument("--query", required=True, help="Your question about a stock, e.g. '帮我看看贵州茅台'")

    # Planner API settings
    parser.add_argument("--planner-api-key", default="", help="Planner API key")
    parser.add_argument("--planner-base-url", default="", help="Planner API base URL")
    parser.add_argument("--planner-model", default="", help="Planner model name (default: gpt-4o)")

    # Other settings
    parser.add_argument("--max-steps", type=int, default=0, help="Max agent steps")
    parser.add_argument("-v", "--verbose", action="store_true", help="Verbose output")
    parser.add_argument("--trace", action="store_true", help="Enable execution tracing")
    parser.add_argument("--trace-dir", default=".", help="Directory for trace output files")

    return parser


def load_config(argv: list[str] | None = None) -> AgentConfig:
    """
    Load configuration from .env + CLI args.

    Priority: CLI args > env vars > defaults
    """
    _load_dotenv()

    parser = build_parser()
    args = parser.parse_args(argv)

    def pick(cli_value: str, env_name: str, default: str) -> str:
        if cli_value:
            return cli_value
        env_value = os.environ.get(env_name, "")
        if env_value:
            return env_value
        return default

    def pick_int(cli_value: int, env_name: str, default: int) -> int:
        if cli_value > 0:
            return cli_value
        env_value = os.environ.get(env_name, "")
        if env_value:
            return int(env_value)
        return default

    config = AgentConfig(
        planner_api_key=pick(args.planner_api_key, "PLANNER_API_KEY", ""),
        planner_base_url=pick(args.planner_base_url, "PLANNER_BASE_URL", ""),
        planner_model=pick(args.planner_model, "PLANNER_MODEL", "gpt-4o"),
        max_steps=pick_int(args.max_steps, "MAX_STEPS", 10),
        query=args.query,
        verbose=args.verbose,
        trace=args.trace,
        trace_dir=args.trace_dir,
    )

    return config
