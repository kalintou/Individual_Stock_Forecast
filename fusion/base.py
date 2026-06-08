"""
Abstract base class for fusion modules.

The fusion module converts tool results into unified EvidenceItem objects,
validates their quality, and manages the evidence lifecycle.
"""

from abc import ABC, abstractmethod

from core.schemas import ToolResult, EvidenceItem
from core.errors import FusionError


class BaseFusion(ABC):
    """
    Abstract base class for evidence fusion.

    Fusion bridges the gap between raw tool outputs and the uniform
    EvidenceItem format used by the planner.
    """

    @property
    @abstractmethod
    def name(self) -> str:
        """Return the name of this fusion module for logging."""
        raise NotImplementedError

    @abstractmethod
    def tool_result_to_evidence(self, tool_result: ToolResult) -> EvidenceItem:
        """
        Convert a tool execution result into an EvidenceItem.

        This is called by factor analysis nodes after a tool runs,
        to add the tool's output to the evidence log.

        Args:
            tool_result: The result returned by the tool executor

        Returns:
            An EvidenceItem with source=tool_result.tool_name

        Raises:
            FusionError: If conversion fails
        """
        raise NotImplementedError

    @abstractmethod
    def format_check(self, evidence: EvidenceItem) -> tuple[bool, str]:
        """
        Validate the format and content quality of an evidence item.

        Args:
            evidence: The evidence item to check

        Returns:
            (is_valid, error_message): True if valid, False with reason if invalid
        """
        raise NotImplementedError

    def validate_evidence(self, evidence: EvidenceItem) -> EvidenceItem:
        """
        Validate evidence and raise FusionError if invalid.

        This is a convenience wrapper around format_check() that raises
        instead of returning a tuple.
        """
        is_valid, msg = self.format_check(evidence)
        if not is_valid:
            raise FusionError(
                f"Evidence validation failed: {msg}",
                details={
                    "source": evidence.source,
                    "content_preview": evidence.content[:200] if evidence.content else "",
                    "error": msg,
                },
            )
        return evidence
