from __future__ import annotations

import json
import random
from pathlib import Path

import httpx
import pytest

from ptbr_benchmark.domain.models import Completion, DomainError, Usage
from ptbr_benchmark.providers.base import CompletionRequest, ProviderError, estimate_tokens
from ptbr_benchmark.providers.baseline import BASELINE_MODEL, BaselineProvider
from ptbr_benchmark.providers.cascade import CascadeProvider
from ptbr_benchmark.providers.http import AnthropicProvider, OpenAIProvider
from ptbr_benchmark.providers.pricing import ModelPrice, PricingTable, load_pricing
from ptbr_benchmark.tasks.base import TaskDefinition
from tests.conftest import make_completion


class ScriptedProvider:
    """Devolve respostas em sequência; útil para cascata e retry."""

    name = "scripted"

    def __init__(self, *responses: Completion | ProviderError) -> None:
        self._responses = list(responses)
        self.calls: list[CompletionRequest] = []

    def complete(self, request: CompletionRequest) -> Completion:
        self.calls.append(request)
        response = self._responses.pop(0)
        if isinstance(response, ProviderError):
            raise response
        return response


def request_for(task: TaskDefinition, item_id: str = "x") -> CompletionRequest:
    item = task.load_items()[0]
    prompt = task.load_prompts()["minimal"]
    return task.build_request(item, prompt, model="cheap", seed=1)


class TestBase:
    def test_request_invariants(self) -> None:
        with pytest.raises(DomainError):
            CompletionRequest(model="m", system="s", user="   ")
        with pytest.raises(DomainError):
            CompletionRequest(model="m", system="s", user="u", max_tokens=0)
        with pytest.raises(DomainError):
            CompletionRequest(model="m", system="s", user="u", temperature=3.0)

    def test_estimate_tokens_floor(self) -> None:
        assert estimate_tokens("") == 1
        assert estimate_tokens("a" * 40) == 10


class TestPricing:
    def test_cost_and_prefix_match(self) -> None:
        table = PricingTable(as_of="2026-01-01", prices={"gpt-x": ModelPrice(1.0, 2.0)})
        price = table.price_for("gpt-x-2026-05-01")
        assert price is not None
        assert price.cost(Usage(input_tokens=1_000_000, output_tokens=500_000)) == 2.0
        assert table.price_for("unknown") is None

    def test_most_specific_price_prefix_wins(self) -> None:
        generic = ModelPrice(10.0, 20.0)
        specific = ModelPrice(1.0, 2.0)
        table = PricingTable(
            as_of="2026-01-01",
            prices={"model": generic, "model-mini": specific},
        )
        assert table.price_for("model-mini-2026-01-01") == specific

    def test_bundled_table_loads_and_has_baseline(self) -> None:
        table = load_pricing()
        assert table.as_of
        assert table.price_for(BASELINE_MODEL) == ModelPrice(0.0, 0.0)

    def test_missing_file(self, tmp_path: Path) -> None:
        with pytest.raises(DomainError, match="não encontrada"):
            load_pricing(tmp_path / "nope.json")


class TestBaseline:
    def test_uses_task_rules_and_marks_estimated_usage(
        self, tasks: dict[str, TaskDefinition]
    ) -> None:
        task = tasks["ticket_routing"]
        provider = BaselineProvider(tasks)
        completion = provider.complete(request_for(task))
        assert completion.model == BASELINE_MODEL
        assert completion.usage.estimated is False
        assert completion.usage.total_tokens == 0
        parsed = json.loads(completion.text)
        assert "category" in parsed

    def test_unknown_task(self, tasks: dict[str, TaskDefinition]) -> None:
        provider = BaselineProvider(tasks)
        request = CompletionRequest(model="m", system="s", user="u", metadata={"task": "nope"})
        with pytest.raises(ProviderError, match="sem tarefa"):
            provider.complete(request)


class TestCascade:
    def test_no_escalation_when_primary_is_confident(
        self, tasks: dict[str, TaskDefinition], pricing: PricingTable
    ) -> None:
        task = tasks["ticket_routing"]
        primary = ScriptedProvider(make_completion('{"category": "cobranca", "confidence": 0.9}'))
        fallback = ScriptedProvider()
        cascade = CascadeProvider(
            primary=primary,
            primary_model="cheap",
            fallback=fallback,
            fallback_model="expensive",
            tasks=tasks,
            pricing=pricing,
        )
        completion = cascade.complete(request_for(task))
        assert completion.model == "cheap"
        assert cascade.escalations == 0 and cascade.total == 1
        assert fallback.calls == []
        assert primary.calls[0].model == "cheap"

    def test_escalates_on_low_confidence_and_sums_cost(
        self, tasks: dict[str, TaskDefinition], pricing: PricingTable
    ) -> None:
        task = tasks["ticket_routing"]
        primary = ScriptedProvider(make_completion('{"category": "cobranca", "confidence": 0.3}'))
        fallback = ScriptedProvider(
            make_completion(
                '{"category": "fraude_seguranca", "confidence": 0.95}', model="expensive"
            )
        )
        cascade = CascadeProvider(
            primary=primary,
            primary_model="cheap",
            fallback=fallback,
            fallback_model="expensive",
            tasks=tasks,
            pricing=pricing,
        )
        completion = cascade.complete(request_for(task))
        assert completion.model == "cheap+expensive"
        assert completion.usage.input_tokens == 200
        assert completion.latency_ms == 20.0
        assert completion.attempts == 2
        assert cascade.escalation_rate == 1.0
        assert fallback.calls[0].model == "expensive"
        cheap_cost = (100 * 1.0 + 20 * 2.0) / 1_000_000
        expensive_cost = (100 * 10.0 + 20 * 30.0) / 1_000_000
        assert completion.cost_usd == pytest.approx(cheap_cost + expensive_cost)
        assert cascade.name == "cascade[scripted:cheap->scripted:expensive]"

    def test_escalates_on_unparseable_output(
        self, tasks: dict[str, TaskDefinition], pricing: PricingTable
    ) -> None:
        task = tasks["ticket_routing"]
        primary = ScriptedProvider(make_completion("não sei"))
        fallback = ScriptedProvider(make_completion('{"category": "elogio", "confidence": 0.9}'))
        cascade = CascadeProvider(
            primary=primary,
            primary_model="cheap",
            fallback=fallback,
            fallback_model="expensive",
            tasks=tasks,
            pricing=pricing,
        )
        cascade.complete(request_for(task))
        assert cascade.escalations == 1

    def test_empty_rate(self, tasks: dict[str, TaskDefinition], pricing: PricingTable) -> None:
        cascade = CascadeProvider(
            primary=ScriptedProvider(),
            primary_model="a",
            fallback=ScriptedProvider(),
            fallback_model="b",
            tasks=tasks,
            pricing=pricing,
        )
        assert cascade.escalation_rate == 0.0

    def test_missing_price_fails_closed(self, tasks: dict[str, TaskDefinition]) -> None:
        task = tasks["ticket_routing"]
        cascade = CascadeProvider(
            primary=ScriptedProvider(make_completion("não parseia", model="unknown")),
            primary_model="unknown",
            fallback=ScriptedProvider(make_completion("{}", model="also-unknown")),
            fallback_model="also-unknown",
            tasks=tasks,
            pricing=PricingTable(as_of="2026-01-01", prices={}),
        )
        with pytest.raises(DomainError, match="preço ausente"):
            cascade.complete(request_for(task))


def _client(handler: httpx.MockTransport) -> httpx.Client:
    return httpx.Client(transport=handler)


class TestAnthropic:
    def test_requires_key(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
        with pytest.raises(ProviderError, match="ANTHROPIC_API_KEY"):
            AnthropicProvider()

    def test_success_parses_content_and_usage(self) -> None:
        seen: dict[str, object] = {}

        def handler(request: httpx.Request) -> httpx.Response:
            seen["headers"] = dict(request.headers)
            seen["body"] = json.loads(request.content)
            return httpx.Response(
                200,
                json={
                    "model": "claude-x",
                    "content": [
                        {"type": "text", "text": "olá "},
                        {"type": "tool_use", "id": "t"},
                        {"type": "text", "text": "mundo"},
                    ],
                    "usage": {"input_tokens": 12, "output_tokens": 3},
                },
            )

        provider = AnthropicProvider(api_key="k", client=_client(httpx.MockTransport(handler)))
        completion = provider.complete(
            CompletionRequest(model="claude-x", system="sys", user="usr", seed=3)
        )
        assert completion.text == "olá mundo"
        assert completion.model == "claude-x"
        assert completion.usage == Usage(12, 3)
        assert seen["headers"]["x-api-key"] == "k"
        body = seen["body"]
        assert isinstance(body, dict) and body["system"] == "sys"
        assert body["messages"] == [{"role": "user", "content": "usr"}]

    @pytest.mark.parametrize(
        ("status", "retryable"), [(429, True), (500, True), (503, True), (400, False), (401, False)]
    )
    def test_status_classification(self, status: int, retryable: bool) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(status, text="erro")

        provider = AnthropicProvider(api_key="k", client=_client(httpx.MockTransport(handler)))
        with pytest.raises(ProviderError) as info:
            provider.complete(CompletionRequest(model="m", system="s", user="u"))
        assert info.value.retryable is retryable
        assert info.value.status_code == status

    def test_timeout_and_transport_errors_are_retryable(self) -> None:
        def timeout(request: httpx.Request) -> httpx.Response:
            raise httpx.ReadTimeout("lento", request=request)

        def broken(request: httpx.Request) -> httpx.Response:
            raise httpx.ConnectError("sem rede", request=request)

        for handler in (timeout, broken):
            provider = AnthropicProvider(api_key="k", client=_client(httpx.MockTransport(handler)))
            with pytest.raises(ProviderError) as info:
                provider.complete(CompletionRequest(model="m", system="s", user="u"))
            assert info.value.retryable

    def test_non_json_body_is_retryable(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, text="<html>gateway</html>")

        provider = AnthropicProvider(api_key="k", client=_client(httpx.MockTransport(handler)))
        with pytest.raises(ProviderError, match="não é JSON"):
            provider.complete(CompletionRequest(model="m", system="s", user="u"))


class TestOpenAI:
    def test_requires_key(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("OPENAI_API_KEY", raising=False)
        with pytest.raises(ProviderError, match="OPENAI_API_KEY"):
            OpenAIProvider()

    def test_success_with_seed(self) -> None:
        seen: dict[str, object] = {}

        def handler(request: httpx.Request) -> httpx.Response:
            seen["body"] = json.loads(request.content)
            seen["auth"] = request.headers["authorization"]
            return httpx.Response(
                200,
                json={
                    "model": "gpt-x",
                    "choices": [{"message": {"content": "resposta"}}],
                    "usage": {"prompt_tokens": 5, "completion_tokens": 2},
                },
            )

        provider = OpenAIProvider(api_key="k", client=_client(httpx.MockTransport(handler)))
        completion = provider.complete(
            CompletionRequest(model="gpt-x", system="s", user="u", seed=11)
        )
        assert completion.text == "resposta"
        assert completion.usage == Usage(5, 2)
        assert seen["auth"] == "Bearer k"
        body = seen["body"]
        assert isinstance(body, dict) and body["seed"] == 11

    def test_empty_choices_is_retryable(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json={"choices": []})

        provider = OpenAIProvider(api_key="k", client=_client(httpx.MockTransport(handler)))
        with pytest.raises(ProviderError, match="sem choices") as info:
            provider.complete(CompletionRequest(model="m", system="s", user="u"))
        assert info.value.retryable

    def test_null_content_becomes_empty_text(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(
                200, json={"choices": [{"message": {"content": None}}], "usage": {}}
            )

        provider = OpenAIProvider(api_key="k", client=_client(httpx.MockTransport(handler)))
        completion = provider.complete(CompletionRequest(model="m", system="s", user="u"))
        assert completion.text == ""
        assert completion.usage.input_tokens > 0
        assert completion.usage.output_tokens == 0
        assert completion.usage.estimated is True

    def test_anthropic_estimates_missing_usage(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(
                200,
                json={"model": "claude-x", "content": [{"type": "text", "text": "ok"}]},
            )

        provider = AnthropicProvider(api_key="k", client=_client(httpx.MockTransport(handler)))
        completion = provider.complete(
            CompletionRequest(model="claude-x", system="system", user="prompt")
        )
        assert completion.usage.estimated is True
        assert completion.usage.total_tokens > 0


def test_scripted_provider_is_deterministic(rng: random.Random) -> None:
    provider = ScriptedProvider(make_completion("a"), make_completion("b"))
    request = CompletionRequest(model="m", system="s", user="u")
    assert provider.complete(request).text == "a"
    assert provider.complete(request).text == "b"
