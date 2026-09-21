"""Roteamento em cascata.

Um modelo barato responde primeiro. Se a tarefa decide que a resposta não
é confiável (não parseia, rótulo inválido, confiança baixa, campo crítico
ausente), o item escala para um modelo maior. Custo e latência somam; o
relatório mostra a fração escalada. É a técnica de redução de custo mais
simples que funciona, e por isso está aqui e não em um artigo.
"""

from __future__ import annotations

from collections.abc import Mapping
from threading import Lock

from ptbr_benchmark.domain.models import Completion, DomainError, Usage
from ptbr_benchmark.providers.base import CompletionRequest, Provider
from ptbr_benchmark.providers.pricing import PricingTable
from ptbr_benchmark.tasks.base import TaskDefinition


class CascadeProvider:
    def __init__(
        self,
        *,
        primary: Provider,
        primary_model: str,
        fallback: Provider,
        fallback_model: str,
        tasks: Mapping[str, TaskDefinition],
        pricing: PricingTable,
    ) -> None:
        self._primary = primary
        self._primary_model = primary_model
        self._fallback = fallback
        self._fallback_model = fallback_model
        self._tasks = dict(tasks)
        self._pricing = pricing
        self._counter_lock = Lock()
        self._escalations = 0
        self._total = 0

    @property
    def escalations(self) -> int:
        with self._counter_lock:
            return self._escalations

    @property
    def total(self) -> int:
        with self._counter_lock:
            return self._total

    @property
    def name(self) -> str:
        primary = f"{self._primary.name}:{self._primary_model}"
        fallback = f"{self._fallback.name}:{self._fallback_model}"
        return f"cascade[{primary}->{fallback}]"

    @property
    def escalation_rate(self) -> float:
        with self._counter_lock:
            return self._escalations / self._total if self._total else 0.0

    def reset_counters(self) -> None:
        """Reinicia métricas após um preflight que não pertence à rodada."""
        with self._counter_lock:
            self._escalations = 0
            self._total = 0

    def complete(self, request: CompletionRequest) -> Completion:
        with self._counter_lock:
            self._total += 1
        task = self._tasks[str(request.metadata["task"])]
        first = self._primary.complete(_with_model(request, self._primary_model))
        if not task.needs_escalation(task.parse(first.text)):
            return first

        with self._counter_lock:
            self._escalations += 1
        second = self._fallback.complete(_with_model(request, self._fallback_model))
        return Completion(
            text=second.text,
            model=f"{self._primary_model}+{self._fallback_model}",
            usage=Usage(
                input_tokens=first.usage.input_tokens + second.usage.input_tokens,
                output_tokens=first.usage.output_tokens + second.usage.output_tokens,
                estimated=first.usage.estimated or second.usage.estimated,
            ),
            latency_ms=first.latency_ms + second.latency_ms,
            cached=first.cached and second.cached,
            attempts=first.attempts + second.attempts,
            cost_usd=self._cost(first) + self._cost(second),
        )

    def _cost(self, completion: Completion) -> float:
        if completion.cost_usd is not None:
            return completion.cost_usd
        price = self._pricing.price_for(completion.model)
        if price is None:
            raise DomainError(
                f"preço ausente para {completion.model!r}; cascata não pode publicar custo zero"
            )
        return price.cost(completion.usage)


def _with_model(request: CompletionRequest, model: str) -> CompletionRequest:
    return CompletionRequest(
        model=model,
        system=request.system,
        user=request.user,
        max_tokens=request.max_tokens,
        temperature=request.temperature,
        seed=request.seed,
        metadata=request.metadata,
    )
