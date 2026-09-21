"""Modelos de domínio do harness.

Tudo aqui é imutável e independente de provedor, de banco e de formato de
relatório. As regras de negócio (o que é um item válido, o que é uma
pontuação válida, como uma execução é identificada) vivem nestas classes.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any


class DomainError(ValueError):
    """Invariante de domínio violada."""


class Split(StrEnum):
    PUBLIC = "public"
    HOLDOUT = "holdout"


class ScoringKind(StrEnum):
    EXACT = "exact"
    FIELDWISE = "fieldwise"
    CLASSIFICATION = "classification"
    REFUSAL = "refusal"
    JUDGE = "judge"


def utc_now() -> datetime:
    return datetime.now(UTC)


def stable_hash(payload: Any) -> str:
    """SHA-256 de uma estrutura JSON serializada de forma canônica."""
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


@dataclass(frozen=True, slots=True)
class Item:
    """Um exemplo do dataset com gabarito."""

    id: str
    task: str
    input: dict[str, Any]
    expected: dict[str, Any]
    split: Split = Split.PUBLIC
    tags: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not self.id.strip():
            raise DomainError("item id é obrigatório")
        if not self.task.strip():
            raise DomainError("item task é obrigatório")
        if not self.input:
            raise DomainError(f"item {self.id!r} sem input")
        if not self.expected:
            raise DomainError(f"item {self.id!r} sem expected")

    @property
    def content_hash(self) -> str:
        return stable_hash({"input": self.input, "expected": self.expected})

    @property
    def scenario_family(self) -> str:
        """Gold scenario shared by controlled surface-form variants."""
        return self.id.split("--", 1)[0]


@dataclass(frozen=True, slots=True)
class Prompt:
    """Um template de prompt versionado por conteúdo."""

    name: str
    template: str

    def __post_init__(self) -> None:
        if not self.template.strip():
            raise DomainError(f"prompt {self.name!r} vazio")

    @property
    def version(self) -> str:
        return hashlib.sha256(self.template.encode("utf-8")).hexdigest()[:12]

    def render(self, **values: Any) -> str:
        try:
            return self.template.format(**values)
        except KeyError as exc:
            raise DomainError(f"prompt {self.name!r} exige variável {exc}") from exc


@dataclass(frozen=True, slots=True)
class Usage:
    input_tokens: int
    output_tokens: int
    estimated: bool = False

    def __post_init__(self) -> None:
        if self.input_tokens < 0 or self.output_tokens < 0:
            raise DomainError("tokens não podem ser negativos")

    @property
    def total_tokens(self) -> int:
        return self.input_tokens + self.output_tokens


@dataclass(frozen=True, slots=True)
class Completion:
    """Resposta bruta de um provedor para um único prompt."""

    text: str
    model: str
    usage: Usage
    latency_ms: float
    cached: bool = False
    attempts: int = 1
    error: str | None = None
    cost_usd: float | None = None
    """Custo já calculado pelo provedor, quando ele envolve mais de um modelo."""

    def __post_init__(self) -> None:
        if self.latency_ms < 0:
            raise DomainError("latência não pode ser negativa")
        if self.attempts < 1:
            raise DomainError("attempts deve ser pelo menos 1")
        if self.cost_usd is not None and self.cost_usd < 0:
            raise DomainError("custo não pode ser negativo")


@dataclass(frozen=True, slots=True)
class Score:
    """Pontuação normalizada em [0, 1] com detalhe por dimensão."""

    value: float
    kind: ScoringKind
    details: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not 0.0 <= self.value <= 1.0:
            raise DomainError(f"score fora de [0, 1]: {self.value}")


@dataclass(frozen=True, slots=True)
class Observation:
    """Um item, uma repetição, um modelo, um prompt: a unidade atômica de medida."""

    item_id: str
    task: str
    provider: str
    model: str
    prompt_name: str
    prompt_version: str
    repetition: int
    completion: Completion
    score: Score
    cost_usd: float

    def __post_init__(self) -> None:
        if self.repetition < 0:
            raise DomainError("repetition não pode ser negativa")
        if self.cost_usd < 0:
            raise DomainError("custo não pode ser negativo")


@dataclass(frozen=True, slots=True)
class RunSpec:
    """Configuração completa de uma execução, suficiente para reproduzi-la."""

    tasks: tuple[str, ...]
    provider: str
    model: str
    prompt_name: str
    repetitions: int
    seed: int
    split: Split
    limit: int | None = None

    def __post_init__(self) -> None:
        if not self.tasks:
            raise DomainError("execução exige pelo menos uma tarefa")
        if self.repetitions < 1:
            raise DomainError("repetitions deve ser pelo menos 1")
        if self.limit is not None and self.limit < 1:
            raise DomainError("limit deve ser positivo")

    @property
    def run_id(self) -> str:
        return stable_hash(
            {
                "tasks": sorted(self.tasks),
                "provider": self.provider,
                "model": self.model,
                "prompt": self.prompt_name,
                "repetitions": self.repetitions,
                "seed": self.seed,
                "split": self.split.value,
                "limit": self.limit,
            }
        )[:16]


@dataclass(frozen=True, slots=True)
class RunResult:
    spec: RunSpec
    started_at: datetime
    finished_at: datetime
    observations: tuple[Observation, ...]
    dataset_hashes: dict[str, str]
    harness_version: str

    def __post_init__(self) -> None:
        if self.finished_at < self.started_at:
            raise DomainError("finished_at anterior a started_at")

    @property
    def total_cost_usd(self) -> float:
        return sum(item.cost_usd for item in self.observations)
