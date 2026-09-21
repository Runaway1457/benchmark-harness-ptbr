"""Contrato de provedor.

O harness não depende de SDK de nenhum fornecedor. Cada provedor é um
adaptador HTTP fino que devolve texto, uso de tokens e latência. Isso mantém
a comparação honesta: o mesmo prompt, o mesmo parser, o mesmo pontuador.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol

from ptbr_benchmark.domain.models import Completion, DomainError


class ProviderError(RuntimeError):
    """Falha de provedor. `retryable` indica se vale tentar de novo."""

    def __init__(self, message: str, *, retryable: bool, status_code: int | None = None) -> None:
        super().__init__(message)
        self.retryable = retryable
        self.status_code = status_code


@dataclass(frozen=True, slots=True)
class CompletionRequest:
    model: str
    system: str
    user: str
    max_tokens: int = 1024
    temperature: float = 0.0
    seed: int | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.user.strip():
            raise DomainError("prompt de usuário vazio")
        if self.max_tokens < 1:
            raise DomainError("max_tokens deve ser positivo")
        if not 0.0 <= self.temperature <= 2.0:
            raise DomainError("temperature fora de [0, 2]")


class Provider(Protocol):
    @property
    def name(self) -> str: ...

    def complete(self, request: CompletionRequest) -> Completion: ...


def estimate_tokens(text: str) -> int:
    """Estimativa grosseira para provedores que não devolvem uso.

    Português tem mais caracteres por token que inglês. Quatro caracteres por
    token é conservador. O resultado é marcado como estimado e nunca entra em
    comparação de custo sem essa marca.
    """
    return max(1, len(text) // 4)
