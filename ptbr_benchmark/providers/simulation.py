"""Controle positivo sintético para demonstrar o harness sem chamar APIs.

O provedor consulta o gabarito diretamente nas tarefas que recebeu. O gabarito
nunca entra em ``CompletionRequest`` e, portanto, não pode alcançar adaptadores
HTTP por acidente.
"""

from __future__ import annotations

import hashlib
import json
import random
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from ptbr_benchmark.domain.models import Completion, DomainError, Item, Split, Usage
from ptbr_benchmark.providers.base import CompletionRequest, estimate_tokens
from ptbr_benchmark.tasks.base import TaskDefinition

INJECTED_PROMPT_EFFECT = 0.035


@dataclass(frozen=True, slots=True)
class SimulationProfile:
    quality: dict[str, float]
    latency_ms: float
    output_tokens: int


PROFILES: dict[str, SimulationProfile] = {
    "sim-economy-v1": SimulationProfile(
        quality={
            "fiscal_extraction": 0.89,
            "ticket_routing": 0.83,
            "lgpd_refusal": 0.81,
            "grounded_qa": 0.72,
            "regional_ptbr": 0.78,
        },
        latency_ms=430.0,
        output_tokens=82,
    ),
    "sim-frontier-v1": SimulationProfile(
        quality={
            "fiscal_extraction": 0.97,
            "ticket_routing": 0.93,
            "lgpd_refusal": 0.92,
            "grounded_qa": 0.87,
            "regional_ptbr": 0.91,
        },
        latency_ms=1180.0,
        output_tokens=126,
    ),
}


def injected_prompt_effect(model: str, task: str) -> float | None:
    """Return the effective probability lift after the simulator's safety cap."""
    profile = PROFILES.get(model)
    if profile is None or task not in profile.quality:
        return None
    base = profile.quality[task]
    return min(0.995, base + INJECTED_PROMPT_EFFECT) - base


class SimulationProvider:
    name = "simulation"

    def __init__(self, tasks: Mapping[str, TaskDefinition]) -> None:
        self._items: dict[tuple[str, str], Item] = {}
        for task in tasks.values():
            for item in task.load_items(Split.PUBLIC):
                self._items[(task.name, item.id)] = item
            if task.dataset_path(Split.HOLDOUT).exists():
                for item in task.load_items(Split.HOLDOUT):
                    self._items[(task.name, item.id)] = item

    def complete(self, request: CompletionRequest) -> Completion:
        profile = PROFILES.get(request.model)
        if profile is None:
            raise DomainError(
                f"perfil simulado desconhecido: {request.model!r}; "
                f"use {', '.join(sorted(PROFILES))}"
            )
        task = str(request.metadata.get("task", ""))
        item_id = str(request.metadata.get("item_id", ""))
        item = self._items.get((task, item_id))
        if item is None or task not in profile.quality:
            raise DomainError(f"item {task}:{item_id} ausente no controle sintético")

        rng = _rng(request)
        prompt_name = str(request.metadata.get("prompt_name", "minimal"))
        probability = min(
            0.995,
            profile.quality[task] + (INJECTED_PROMPT_EFFECT if prompt_name == "optimized" else 0.0),
        )
        output = _candidate(item, correct=rng.random() < probability, rng=rng)
        return Completion(
            text=json.dumps(output, ensure_ascii=False),
            model=request.model,
            usage=Usage(
                input_tokens=estimate_tokens(request.system + "\n" + request.user),
                output_tokens=max(8, round(profile.output_tokens * rng.uniform(0.72, 1.28))),
                estimated=True,
            ),
            latency_ms=round(profile.latency_ms * rng.lognormvariate(0.0, 0.28), 2),
        )


def _rng(request: CompletionRequest) -> random.Random:
    material = "|".join(
        (
            request.model,
            str(request.metadata.get("task")),
            str(request.metadata.get("item_id")),
            str(request.metadata.get("prompt_name")),
            str(request.seed),
        )
    )
    return random.Random(hashlib.sha256(material.encode()).hexdigest())


def _candidate(item: Item, *, correct: bool, rng: random.Random) -> dict[str, Any]:
    expected = item.expected
    if item.task == "ticket_routing":
        labels = (
            "cobranca",
            "acesso_login",
            "bug_tecnico",
            "cancelamento",
            "duvida_produto",
            "comercial",
            "elogio",
            "fraude_seguranca",
        )
        category = str(expected["category"])
        if not correct:
            category = rng.choice([label for label in labels if label != category])
        return {"category": category, "confidence": round(rng.uniform(0.62, 0.96), 2)}
    if item.task == "lgpd_refusal":
        refuse = bool(expected["should_refuse"])
        return {
            "refuse": refuse if correct else not refuse,
            "justification": "decisão baseada na finalidade, necessidade e base legal informadas",
        }
    if item.task == "regional_ptbr":
        answer = str(expected["answer"])
        if not correct:
            answer = rng.choice([letter for letter in "ABCD" if letter != answer])
        return {"answer": answer}
    if item.task == "grounded_qa":
        if correct:
            return {
                "answer": expected.get("answer"),
                "citations": list(expected.get("supporting_ids", [])),
            }
        valid_ids = [str(p["id"]) for p in item.input["passages"]]
        wrong_ids = [i for i in valid_ids if i not in expected.get("supporting_ids", [])]
        return {
            "answer": "A informação não está suficientemente clara nos trechos.",
            "citations": [rng.choice(wrong_ids)] if wrong_ids else [],
        }
    if item.task == "fiscal_extraction":
        return _fiscal_candidate(dict(expected), correct=correct, rng=rng)
    raise DomainError(f"tarefa não suportada pela simulação: {item.task!r}")


def _fiscal_candidate(
    result: dict[str, Any], *, correct: bool, rng: random.Random
) -> dict[str, Any]:
    if correct:
        return result
    field = rng.choice(["numero", "serie", "valor_total", "cfop", "emitente_uf"])
    if field in {"numero", "serie"}:
        result[field] = int(result[field]) + rng.choice((-2, -1, 1, 2))
    elif field == "valor_total":
        result[field] = "0,00"
    elif field == "cfop":
        result[field] = "0000"
    else:
        result[field] = "SP" if str(result[field]) != "SP" else "RJ"
    return result
