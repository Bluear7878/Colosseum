from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any

from pydantic import BaseModel, Field

from colosseum.core.models import UsageMetrics


class ProviderExecutionError(RuntimeError):
    """Provider execution failed in a non-recoverable way."""


class ProviderQuotaExceededError(ProviderExecutionError):
    """Provider rejected the request because the paid quota is exhausted."""


class ProviderResult(BaseModel):
    content: str
    json_payload: dict[str, Any] = Field(default_factory=dict)
    usage: UsageMetrics = Field(default_factory=UsageMetrics)
    finish_reason: str = "completed"
    raw_response: Any | None = None


class BaseProvider(ABC):
    @abstractmethod
    async def generate(
        self,
        operation: str,
        instructions: str,
        metadata: dict[str, Any],
    ) -> ProviderResult:
        """Generate content for a planning, debate, or judge operation."""
