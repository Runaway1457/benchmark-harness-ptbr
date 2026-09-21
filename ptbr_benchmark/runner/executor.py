"""Executor de rodadas.

Para cada item, cada repetição: monta a requisição, consulta o cache, chama o
provedor com retry e backoff, interpreta, pontua e registra a observação.
Concorrência limitada por provedor. Falha de provedor após esgotar tentativas
vira observação com erro e pontuação zero: o item conta, o problema fica
visível no relatório em vez de sumir.
"""

from __future__ import annotations

import random
import time
from collections.abc import Callable, Iterable, Sequence
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass

import structlog

from ptbr_benchmark import __version__
from ptbr_benchmark.domain.models import (
    Completion,
    DomainError,
    Item,
    Observation,
    Prompt,
    RunResult,
    RunSpec,
    Score,
    Usage,
    utc_now,
)
from ptbr_benchmark.providers.base import CompletionRequest, Provider, ProviderError
from ptbr_benchmark.providers.pricing import PricingTable
from ptbr_benchmark.runner.cache import CompletionCache, cache_key
from ptbr_benchmark.tasks.base import TaskDefinition

log = structlog.get_logger("ptbr_benchmark.executor")

SleepFn = Callable[[float], None]


@dataclass(frozen=True, slots=True)
class RetryPolicy:
    max_attempts: int = 4
    base_delay_seconds: float = 0.5
    max_delay_seconds: float = 8.0

    def delay(self, attempt: int, rng: random.Random) -> float:
        exponential: float = min(
            self.max_delay_seconds, self.base_delay_seconds * float(2 ** (attempt - 1))
        )
        return exponential * (0.5 + rng.random())


def call_with_retry(
    provider: Provider,
    request: CompletionRequest,
    *,
    policy: RetryPolicy,
    rng: random.Random,
    sleep: SleepFn = time.sleep,
) -> Completion:
    last_error: ProviderError | None = None
    backoff_ms = 0.0
    for attempt in range(1, policy.max_attempts + 1):
        try:
            completion = provider.complete(request)
        except ProviderError as exc:
            last_error = exc
            if not exc.retryable or attempt == policy.max_attempts:
                break
            wait = policy.delay(attempt, rng)
            backoff_ms += wait * 1000
            log.warning(
                "provider.retry",
                provider=provider.name,
                attempt=attempt,
                wait_seconds=round(wait, 2),
                error=str(exc),
            )
            sleep(wait)
            continue
        if attempt > 1:
            return Completion(
                text=completion.text,
                model=completion.model,
                usage=completion.usage,
                latency_ms=backoff_ms + completion.latency_ms,
                cached=completion.cached,
                attempts=attempt,
                cost_usd=completion.cost_usd,
            )
        return completion

    assert last_error is not None
    return Completion(
        text="",
        model=request.model,
        usage=Usage(input_tokens=0, output_tokens=0, estimated=True),
        latency_ms=backoff_ms,
        attempts=policy.max_attempts if last_error.retryable else 1,
        error=str(last_error),
    )


class Executor:
    def __init__(
        self,
        *,
        provider: Provider,
        pricing: PricingTable,
        cache: CompletionCache | None = None,
        retry_policy: RetryPolicy | None = None,
        max_concurrency: int = 4,
        sleep: SleepFn = time.sleep,
    ) -> None:
        if max_concurrency < 1:
            raise ValueError("max_concurrency deve ser positivo")
        self._provider = provider
        self._pricing = pricing
        self._cache = cache
        self._retry = retry_policy or RetryPolicy()
        self._concurrency = max_concurrency
        self._sleep = sleep

    def preflight(self, request: CompletionRequest) -> Completion:
        """Executa uma única chamada não cacheada antes de iniciar a matriz paga."""
        completion = call_with_retry(
            self._provider,
            request,
            policy=self._retry,
            rng=random.Random(cache_key(self._provider.name, request)),
            sleep=self._sleep,
        )
        if completion.error is not None:
            raise DomainError(f"preflight do provedor falhou: {completion.error}")
        if completion.cost_usd is None and self._pricing.price_for(completion.model) is None:
            raise DomainError(
                f"preflight devolveu modelo sem preço {completion.model!r}; "
                "atualize pricing.json antes da rodada"
            )
        return completion

    def run(
        self,
        spec: RunSpec,
        tasks: Sequence[TaskDefinition],
        prompts_by_task: dict[str, Prompt],
    ) -> RunResult:
        started = utc_now()
        rng = random.Random(spec.seed)
        jobs: list[tuple[TaskDefinition, Item, Prompt, int]] = []
        dataset_hashes: dict[str, str] = {}
        for task in tasks:
            items = task.load_items(spec.split)
            dataset_hashes[task.name] = task.dataset_hash(spec.split)
            if spec.limit is not None:
                items = tuple(rng.sample(items, k=min(spec.limit, len(items))))
            prompt = prompts_by_task[task.name]
            jobs.extend(
                (task, item, prompt, repetition)
                for item in items
                for repetition in range(spec.repetitions)
            )

        log.info(
            "run.start",
            run_id=spec.run_id,
            provider=self._provider.name,
            model=spec.model,
            jobs=len(jobs),
            tasks=list(spec.tasks),
        )
        observations = list(self._execute(jobs, spec))
        observations.sort(key=lambda o: (o.task, o.item_id, o.repetition))
        finished = utc_now()
        log.info(
            "run.finish",
            run_id=spec.run_id,
            observations=len(observations),
            cost_usd=round(sum(o.cost_usd for o in observations), 4),
            seconds=round((finished - started).total_seconds(), 1),
        )
        return RunResult(
            spec=spec,
            started_at=started,
            finished_at=finished,
            observations=tuple(observations),
            dataset_hashes=dataset_hashes,
            harness_version=__version__,
        )

    def _execute(
        self,
        jobs: Iterable[tuple[TaskDefinition, Item, Prompt, int]],
        spec: RunSpec,
    ) -> Iterable[Observation]:
        with ThreadPoolExecutor(max_workers=self._concurrency) as pool:
            futures = [
                pool.submit(self._one, task, item, prompt, rep, spec)
                for task, item, prompt, rep in jobs
            ]
            for future in as_completed(futures):
                yield future.result()

    def _one(
        self,
        task: TaskDefinition,
        item: Item,
        prompt: Prompt,
        repetition: int,
        spec: RunSpec,
    ) -> Observation:
        seed = spec.seed * 1000 + repetition
        request = task.build_request(item, prompt, model=spec.model, seed=seed)
        completion = self._complete(request)

        if completion.error is not None:
            score = Score(
                value=0.0,
                kind=task.scoring_kind,
                details={"provider_error": completion.error},
            )
        else:
            parsed = task.parse(completion.text)
            score = task.score(item, parsed)

        if completion.error is not None:
            cost = 0.0
        elif completion.cost_usd is not None:
            cost = completion.cost_usd
        else:
            price = self._pricing.price_for(completion.model)
            if price is None:
                raise DomainError(
                    f"preço ausente para o modelo devolvido {completion.model!r}; "
                    "atualize ptbr_benchmark/providers/pricing.json antes de publicar"
                )
            cost = price.cost(completion.usage)

        # A observação leva o modelo da configuração, não o que respondeu este
        # item: em cascata, itens escalados e não escalados são a mesma
        # configuração e precisam ser agregados juntos.
        return Observation(
            item_id=item.id,
            task=task.name,
            provider=self._provider.name,
            model=spec.model,
            prompt_name=prompt.name,
            prompt_version=prompt.version,
            repetition=repetition,
            completion=completion,
            score=score,
            cost_usd=cost,
        )

    def _complete(self, request: CompletionRequest) -> Completion:
        key = cache_key(self._provider.name, request)
        if self._cache is not None and (cached := self._cache.get(key)) is not None:
            return cached
        completion = call_with_retry(
            self._provider,
            request,
            policy=self._retry,
            rng=random.Random(key),
            sleep=self._sleep,
        )
        if self._cache is not None and completion.error is None:
            self._cache.put(key, self._provider.name, completion)
        return completion
