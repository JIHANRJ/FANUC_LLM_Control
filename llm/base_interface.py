"""Abstract interface for pluggable language model adapters."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any


class LLMInterface(ABC):
    """Defines the model-agnostic parsing contract."""

    @abstractmethod
    def parse(self, text: str) -> dict[str, Any]:
        """Convert free-form user text into a structured command dictionary."""
        raise NotImplementedError
