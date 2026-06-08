"""
Agent status constants.

Defines the possible states an agent can be in during execution.
This is the simplest file in the project — just an enum.
"""

from enum import Enum


class AgentStatus(str, Enum):
    """
    Status of the agent during execution.
    
    The agent transitions through these states as it moves through the graph:
    - RUNNING: Active, making decisions and gathering evidence
    - ANSWERED: Successfully produced a final answer
    - FAILED: Hit an unrecoverable error or explicit failure
    - CLARIFYING: Needs user clarification (reserved for future use)
    """
    RUNNING = "running"
    ANSWERED = "answered"
    FAILED = "failed"
    CLARIFYING = "clarifying"
