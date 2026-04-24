"""Abstract LLM provider interface.

All backends implement this protocol so the rest of the codebase
never depends on a specific LLM API.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable


@runtime_checkable
class LLMProvider(Protocol):
    """Minimal interface for LLM completion.

    Implementations must accept a system prompt and a user prompt and
    return the model's text response.
    """

    def complete(self, system: str, user: str) -> str:
        """Generate a completion.

        Parameters
        ----------
        system:
            The system-level instruction (persona / task framing).
        user:
            The user-level input (the actual content to process).

        Returns
        -------
        str
            The model's text response.
        """
        ...
