"""Adaptadores HTTP para provedores de modelo.

Sem SDK. Cada adaptador conhece um endpoint, um formato de requisição e um
formato de resposta. Erros são classificados em retryable ou não para o
executor decidir.
"""

from __future__ import annotations

import os
from time import perf_counter
from typing import Any

import httpx

from ptbr_benchmark.domain.models import Completion, Usage
from ptbr_benchmark.providers.base import CompletionRequest, ProviderError, estimate_tokens

_RETRYABLE_STATUS = frozenset({408, 409, 425, 429, 500, 502, 503, 504})


def _classify(response: httpx.Response) -> None:
    if response.is_success:
        return
    retryable = response.status_code in _RETRYABLE_STATUS
    detail = response.text[:300]
    raise ProviderError(
        f"HTTP {response.status_code}: {detail}",
        retryable=retryable,
        status_code=response.status_code,
    )


def _post(client: httpx.Client, url: str, *, headers: dict[str, str], body: dict[str, Any]) -> Any:
    try:
        response = client.post(url, headers=headers, json=body)
    except httpx.TimeoutException as exc:
        raise ProviderError("timeout", retryable=True) from exc
    except httpx.HTTPError as exc:
        raise ProviderError(f"erro de transporte: {exc}", retryable=True) from exc
    _classify(response)
    try:
        return response.json()
    except ValueError as exc:
        raise ProviderError("resposta não é JSON", retryable=True) from exc


def _usage_or_estimate(
    raw: dict[str, Any],
    *,
    input_key: str,
    output_key: str,
    request: CompletionRequest,
    text: str,
) -> Usage:
    if input_key in raw and output_key in raw:
        return Usage(
            input_tokens=int(raw[input_key]),
            output_tokens=int(raw[output_key]),
        )
    return Usage(
        input_tokens=estimate_tokens(f"{request.system}\n{request.user}"),
        output_tokens=estimate_tokens(text) if text else 0,
        estimated=True,
    )


class AnthropicProvider:
    name = "anthropic"

    def __init__(
        self,
        *,
        api_key: str | None = None,
        base_url: str = "https://api.anthropic.com",
        timeout_seconds: float = 60.0,
        client: httpx.Client | None = None,
    ) -> None:
        key = api_key or os.environ.get("ANTHROPIC_API_KEY")
        if not key:
            raise ProviderError("ANTHROPIC_API_KEY ausente", retryable=False)
        self._key = key
        self._url = f"{base_url.rstrip('/')}/v1/messages"
        self._client = client or httpx.Client(timeout=timeout_seconds)

    def complete(self, request: CompletionRequest) -> Completion:
        body: dict[str, Any] = {
            "model": request.model,
            "max_tokens": request.max_tokens,
            "temperature": request.temperature,
            "system": request.system,
            "messages": [{"role": "user", "content": request.user}],
        }
        headers = {
            "x-api-key": self._key,
            "anthropic-version": "2023-06-01",
            "content-type": "application/json",
        }
        started = perf_counter()
        payload = _post(self._client, self._url, headers=headers, body=body)
        latency = (perf_counter() - started) * 1000

        blocks = payload.get("content", [])
        text = "".join(block.get("text", "") for block in blocks if block.get("type") == "text")
        usage = payload.get("usage", {})
        return Completion(
            text=text,
            model=str(payload.get("model", request.model)),
            usage=_usage_or_estimate(
                usage,
                input_key="input_tokens",
                output_key="output_tokens",
                request=request,
                text=text,
            ),
            latency_ms=latency,
        )


class OpenAIProvider:
    name = "openai"

    def __init__(
        self,
        *,
        api_key: str | None = None,
        base_url: str = "https://api.openai.com",
        timeout_seconds: float = 60.0,
        client: httpx.Client | None = None,
    ) -> None:
        key = api_key or os.environ.get("OPENAI_API_KEY")
        if not key:
            raise ProviderError("OPENAI_API_KEY ausente", retryable=False)
        self._key = key
        self._url = f"{base_url.rstrip('/')}/v1/chat/completions"
        self._client = client or httpx.Client(timeout=timeout_seconds)

    def complete(self, request: CompletionRequest) -> Completion:
        body: dict[str, Any] = {
            "model": request.model,
            "max_tokens": request.max_tokens,
            "temperature": request.temperature,
            "messages": [
                {"role": "system", "content": request.system},
                {"role": "user", "content": request.user},
            ],
        }
        if request.seed is not None:
            body["seed"] = request.seed
        headers = {"authorization": f"Bearer {self._key}", "content-type": "application/json"}
        started = perf_counter()
        payload = _post(self._client, self._url, headers=headers, body=body)
        latency = (perf_counter() - started) * 1000

        choices = payload.get("choices") or []
        if not choices:
            raise ProviderError("resposta sem choices", retryable=True)
        message = choices[0].get("message", {})
        text = str(message.get("content") or "")
        usage = payload.get("usage", {})
        return Completion(
            text=text,
            model=str(payload.get("model", request.model)),
            usage=_usage_or_estimate(
                usage,
                input_key="prompt_tokens",
                output_key="completion_tokens",
                request=request,
                text=text,
            ),
            latency_ms=latency,
        )
