"""Provedor de referência por regras.

Não chama nenhum modelo. Executa a solução de referência da tarefa e devolve
o resultado no mesmo formato de texto que um modelo devolveria, para passar
pelo mesmo parser e pelo mesmo pontuador. É o piso da comparação e é o que
permite rodar o pipeline inteiro sem chave de API.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from time import perf_counter

from ptbr_benchmark.domain.models import Completion, Item, Split, Usage
from ptbr_benchmark.providers.base import CompletionRequest, ProviderError
from ptbr_benchmark.tasks.base import TaskDefinition

BASELINE_MODEL = "baseline-rules"


class BaselineProvider:
    name = "baseline"

    def __init__(self, tasks: Mapping[str, TaskDefinition]) -> None:
        self._tasks = dict(tasks)

    def complete(self, request: CompletionRequest) -> Completion:
        task_name = request.metadata.get("task")
        task = self._tasks.get(str(task_name))
        if task is None:
            raise ProviderError(f"baseline sem tarefa {task_name!r}", retryable=False)
        item = Item(
            id=str(request.metadata.get("item_id", "unknown")),
            task=task.name,
            input=dict(request.metadata["input"]),
            expected={"_": None},
            split=Split.PUBLIC,
        )
        started = perf_counter()
        output = task.baseline(item)
        text = json.dumps(output, ensure_ascii=False)
        return Completion(
            text=text,
            model=BASELINE_MODEL,
            # The rules baseline is not a token-billed model. Reporting an
            # estimated token cost would make it look comparable to an API
            # call when it is only a harness/control reference.
            usage=Usage(input_tokens=0, output_tokens=0, estimated=False),
            latency_ms=(perf_counter() - started) * 1000,
        )
