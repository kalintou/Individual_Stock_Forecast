"""
Abstract base class for planner modules.

The planner is the "brain" of the stock forecast agent.
It provides LLM-powered analysis capabilities via a unified generate() interface.
"""

from abc import ABC, abstractmethod


class BasePlanner(ABC):
    """
    Abstract base class for planners.

    The planner provides a unified interface for LLM text generation,
    used by graph nodes for intent parsing, market analysis, factor evaluation,
    strategy generation, and report writing.
    """

    @property
    @abstractmethod
    def name(self) -> str:
        """Return the name of this planner for logging."""
        raise NotImplementedError

    @abstractmethod
    def generate(self, system_prompt: str, user_prompt: str) -> str:
        """
        Generate text using the underlying LLM.

        Args:
            system_prompt: System-level instructions
            user_prompt: User-level input/query

        Returns:
            Generated text response
        """
        raise NotImplementedError
