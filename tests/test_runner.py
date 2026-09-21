from __future__ import annotations

import random
from pathlib import Path

import pytest

from ptbr_benchmark.domain.models import Completion, DomainError, Prompt, RunSpec, Split, Usage
from ptbr_benchmark.providers.base import CompletionRequest, ProviderError
from ptbr_benchmark.providers.baseline import BaselineProvider
from ptbr_benchmark.providers.pricing import PricingTable
from ptbr_benchmark.runner.cache import CompletionCache, cache_key
from ptbr_benchmark.runner.executor import Executor, RetryPolicy, call_with_retry
from ptbr_benchmark.tasks.base import TaskDefinition
from tests.conftest import make_completion
from tests.test_providers import ScriptedProvider


class TestCache:
    def test_key_changes_with_prompt_model_seed_and_provider(self) -> None:
        base = CompletionRequest(model="m", system="s", user="u", seed=1)
        variants = [
            CompletionRequest(model="m2", system="s", user="u", seed=1),
            CompletionRequest(model="m", system="s2", user="u", seed=1),
            CompletionRequest(model="m", system="s", user="u2", seed=1),
            CompletionRequest(model="m", system="s", user="u", seed=2),
            CompletionRequest(model="m", system="s", user="u", seed=1, temperature=0.5),
        ]
        key = cache_key("p", base)
        assert all(cache_key("p", v) != key for v in variants)
        assert cache_key("other", base) != key
        assert cache_key("p", base) == key

    def test_roundtrip_marks_cached_and_preserves_usage(self, tmp_path: Path) -> None:
        cache = CompletionCache(tmp_path / "c.sqlite")
        assert cache.get("k") is None
        original = make_completion("texto", latency_ms=321.0)
        cache.put("k", "p", original)
        hit = cache.get("k")
        assert hit is not None
        assert hit.cached is True
        assert hit.text == "texto"
        assert hit.latency_ms == 321.0
        assert hit.usage == original.usage
        assert cache.count() == 1
        cache.close()

    def test_survives_reopen(self, tmp_path: Path) -> None:
        path = tmp_path / "c.sqlite"
        first = CompletionCache(path)
        first.put("k", "p", make_completion("persistido"))
        first.close()
        second = CompletionCache(path)
        hit = second.get("k")
        assert hit is not None and hit.text == "persistido"
        second.close()


class TestRetry:
    def test_retries_retryable_then_succeeds(self) -> None:
        provider = ScriptedProvider(
            ProviderError("429", retryable=True, status_code=429),
            ProviderError("timeout", retryable=True),
            make_completion("ok"),
        )
        waits: list[float] = []
        completion = call_with_retry(
            provider,
            CompletionRequest(model="m", system="s", user="u"),
            policy=RetryPolicy(max_attempts=4, base_delay_seconds=1.0, max_delay_seconds=4.0),
            rng=random.Random(1),
            sleep=waits.append,
        )
        assert completion.text == "ok"
        assert completion.attempts == 3
        assert len(waits) == 2
        assert waits[1] > waits[0] * 0.5
        assert completion.latency_ms == pytest.approx(sum(waits) * 1000 + 10.0)

    def test_retry_preserves_provider_calculated_cost(self) -> None:
        priced = Completion(
            text="ok",
            model="cascade",
            usage=Usage(input_tokens=10, output_tokens=2),
            latency_ms=25.0,
            cost_usd=0.0042,
        )
        provider = ScriptedProvider(ProviderError("429", retryable=True), priced)
        completion = call_with_retry(
            provider,
            CompletionRequest(model="cascade", system="s", user="u"),
            policy=RetryPolicy(max_attempts=2, base_delay_seconds=0.1),
            rng=random.Random(1),
            sleep=lambda _: None,
        )
        assert completion.cost_usd == 0.0042
        assert completion.attempts == 2

    def test_gives_up_after_max_attempts(self) -> None:
        provider = ScriptedProvider(*[ProviderError("503", retryable=True)] * 3)
        completion = call_with_retry(
            provider,
            CompletionRequest(model="m", system="s", user="u"),
            policy=RetryPolicy(max_attempts=3),
            rng=random.Random(1),
            sleep=lambda _: None,
        )
        assert completion.error == "503"
        assert completion.attempts == 3
        assert completion.text == ""
        assert len(provider.calls) == 3

    def test_non_retryable_fails_immediately(self) -> None:
        provider = ScriptedProvider(ProviderError("401", retryable=False, status_code=401))
        waits: list[float] = []
        completion = call_with_retry(
            provider,
            CompletionRequest(model="m", system="s", user="u"),
            policy=RetryPolicy(max_attempts=4),
            rng=random.Random(1),
            sleep=waits.append,
        )
        assert completion.error == "401"
        assert completion.attempts == 1
        assert waits == []

    def test_backoff_is_capped(self) -> None:
        policy = RetryPolicy(max_attempts=10, base_delay_seconds=1.0, max_delay_seconds=2.0)
        rng = random.Random(5)
        assert all(policy.delay(attempt, rng) <= 3.0 for attempt in range(1, 10))


class TestExecutor:
    def _spec(self, task: str, **overrides: object) -> RunSpec:
        base: dict[str, object] = {
            "tasks": (task,),
            "provider": "baseline",
            "model": "baseline-rules",
            "prompt_name": "minimal",
            "repetitions": 2,
            "seed": 7,
            "split": Split.PUBLIC,
            "limit": 5,
        }
        base.update(overrides)
        return RunSpec(**base)  # type: ignore[arg-type]

    def test_runs_repetitions_and_uses_cache(
        self, tasks: dict[str, TaskDefinition], pricing: PricingTable, tmp_path: Path
    ) -> None:
        task = tasks["ticket_routing"]
        cache = CompletionCache(tmp_path / "c.sqlite")
        executor = Executor(provider=BaselineProvider(tasks), pricing=pricing, cache=cache)
        prompts = {task.name: task.load_prompts()["minimal"]}
        first = executor.run(self._spec(task.name), [task], prompts)
        assert len(first.observations) == 10
        assert all(not o.completion.cached for o in first.observations)
        assert first.dataset_hashes[task.name] == task.dataset_hash()
        assert first.observations == tuple(
            sorted(first.observations, key=lambda o: (o.task, o.item_id, o.repetition))
        )

        second = executor.run(self._spec(task.name), [task], prompts)
        assert all(o.completion.cached for o in second.observations)
        assert [o.score.value for o in second.observations] == [
            o.score.value for o in first.observations
        ]
        cache.close()

    def test_provider_error_becomes_zero_score_observation(
        self, tasks: dict[str, TaskDefinition], pricing: PricingTable
    ) -> None:
        task = tasks["ticket_routing"]
        provider = ScriptedProvider(*[ProviderError("boom", retryable=False)] * 2)
        executor = Executor(
            provider=provider,
            pricing=pricing,
            retry_policy=RetryPolicy(max_attempts=2),
            max_concurrency=1,
            sleep=lambda _: None,
        )
        prompts = {task.name: task.load_prompts()["minimal"]}
        result = executor.run(
            self._spec(task.name, repetitions=1, limit=2, provider="scripted", model="cheap"),
            [task],
            prompts,
        )
        assert len(result.observations) == 2
        assert all(o.score.value == 0.0 for o in result.observations)
        assert all(o.score.details["provider_error"] == "boom" for o in result.observations)
        assert result.total_cost_usd == 0.0

    def test_observation_carries_configured_model_and_provider_cost(
        self, tasks: dict[str, TaskDefinition], pricing: PricingTable
    ) -> None:
        task = tasks["regional_ptbr"]
        precomputed = Completion(
            text='{"answer": "A"}',
            model="cheap+expensive",
            usage=Usage(input_tokens=200, output_tokens=40),
            latency_ms=5.0,
            cost_usd=0.0123,
        )
        provider = ScriptedProvider(precomputed)
        executor = Executor(provider=provider, pricing=pricing, max_concurrency=1)
        prompts = {task.name: task.load_prompts()["minimal"]}
        result = executor.run(
            self._spec(
                task.name, repetitions=1, limit=1, provider="scripted", model="cheap+expensive"
            ),
            [task],
            prompts,
        )
        observation = result.observations[0]
        assert observation.model == "cheap+expensive"
        assert observation.cost_usd == 0.0123

    def test_cost_from_pricing_and_missing_price_fails_closed(
        self, tasks: dict[str, TaskDefinition], pricing: PricingTable
    ) -> None:
        task = tasks["regional_ptbr"]
        provider = ScriptedProvider(
            make_completion('{"answer": "A"}', model="cheap"),
            make_completion('{"answer": "B"}', model="unknown-model"),
        )
        executor = Executor(provider=provider, pricing=pricing, max_concurrency=1)
        prompts = {task.name: task.load_prompts()["minimal"]}
        with pytest.raises(DomainError, match="preço ausente"):
            executor.run(
                self._spec(task.name, repetitions=1, limit=2, provider="scripted", model="cheap"),
                [task],
                prompts,
            )

        priced = ScriptedProvider(make_completion('{"answer": "A"}', model="cheap"))
        result = Executor(provider=priced, pricing=pricing, max_concurrency=1).run(
            self._spec(task.name, repetitions=1, limit=1, provider="scripted", model="cheap"),
            [task],
            prompts,
        )
        assert result.observations[0].cost_usd == pytest.approx((100 * 1.0 + 20 * 2.0) / 1_000_000)

    def test_rejects_bad_concurrency(self, pricing: PricingTable) -> None:
        with pytest.raises(ValueError, match="positivo"):
            Executor(provider=ScriptedProvider(), pricing=pricing, max_concurrency=0)

    def test_seed_differs_per_repetition(
        self, tasks: dict[str, TaskDefinition], pricing: PricingTable
    ) -> None:
        task = tasks["regional_ptbr"]
        provider = ScriptedProvider(*[make_completion('{"answer": "A"}')] * 2)
        executor = Executor(provider=provider, pricing=pricing, max_concurrency=1)
        prompt = Prompt(name="minimal", template=task.load_prompts()["minimal"].template)
        executor.run(
            self._spec(task.name, repetitions=2, limit=1, provider="scripted", model="cheap"),
            [task],
            {task.name: prompt},
        )
        seeds = sorted(call.seed for call in provider.calls if call.seed is not None)
        assert seeds == [7000, 7001]
