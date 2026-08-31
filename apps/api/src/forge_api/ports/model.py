from typing import Protocol

from forge_api.domain.planning import StructuredModelRequest, StructuredModelResult


class ModelProvider(Protocol):
    def complete(self, request: StructuredModelRequest) -> StructuredModelResult:
        pass
