"""Juiz automático com validação de concordância.

Para tarefa de texto livre, um modelo pode pontuar a resposta de outro. Isso
só vale se a concordância com anotação humana for medida. O juiz aqui produz
um rótulo em {correct, partial, incorrect}; a validação compara com uma
amostra anotada e devolve kappa. O relatório recusa publicar pontuação de
juiz sem kappa acima do limiar.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ptbr_benchmark.domain.metrics import cohens_kappa, interpret_kappa
from ptbr_benchmark.domain.models import DomainError, Item
from ptbr_benchmark.providers.base import CompletionRequest, Provider
from ptbr_benchmark.scoring.scorers import parse_json_object

JUDGE_LABELS: frozenset[str] = frozenset({"correct", "partial", "incorrect"})
MINIMUM_KAPPA = 0.6

_JUDGE_SYSTEM = (
    "Você avalia respostas de um assistente corporativo em português brasileiro. "
    "Compare a resposta dada com a resposta de referência. Responda apenas com JSON: "
    '{"label": "correct" | "partial" | "incorrect", "rationale": "uma frase"}. '
    "correct: mesma informação, mesmo sentido. partial: informação incompleta ou com "
    "detalhe errado que não muda a conclusão. incorrect: informação errada, inventada ou ausente."
)

_JUDGE_USER = (
    "Pergunta:\n{question}\n\nResposta de referência:\n{reference}\n\n"
    "Resposta a avaliar:\n{candidate}\n\nJSON:"
)


@dataclass(frozen=True, slots=True)
class Verdict:
    label: str
    rationale: str

    def __post_init__(self) -> None:
        if self.label not in JUDGE_LABELS:
            raise DomainError(f"rótulo de juiz inválido: {self.label}")

    @property
    def value(self) -> float:
        return {"correct": 1.0, "partial": 0.5, "incorrect": 0.0}[self.label]


class LlmJudge:
    def __init__(self, provider: Provider, *, model: str) -> None:
        self._provider = provider
        self._model = model

    @property
    def identity(self) -> str:
        return f"{self._provider.name}:{self._model}"

    def judge(self, *, question: str, reference: str, candidate: str) -> Verdict:
        request = CompletionRequest(
            model=self._model,
            system=_JUDGE_SYSTEM,
            user=_JUDGE_USER.format(question=question, reference=reference, candidate=candidate),
            max_tokens=200,
            temperature=0.0,
        )
        completion = self._provider.complete(request)
        parsed = parse_json_object(completion.text)
        if parsed is None or parsed.get("label") not in JUDGE_LABELS:
            return Verdict(label="incorrect", rationale="juiz devolveu saída inválida")
        return Verdict(label=str(parsed["label"]), rationale=str(parsed.get("rationale", "")))


@dataclass(frozen=True, slots=True)
class JudgeValidation:
    judge: str
    task: str
    sample_size: int
    kappa: float
    interpretation: str
    validated_at: str

    @property
    def accepted(self) -> bool:
        return self.kappa >= MINIMUM_KAPPA

    def to_json(self) -> dict[str, Any]:
        return {
            "judge": self.judge,
            "task": self.task,
            "sample_size": self.sample_size,
            "kappa": round(self.kappa, 4),
            "interpretation": self.interpretation,
            "minimum_kappa": MINIMUM_KAPPA,
            "accepted": self.accepted,
            "validated_at": self.validated_at,
        }


def validate_judge(
    judge: LlmJudge,
    *,
    task_name: str,
    items: dict[str, Item],
    human_labels: list[dict[str, Any]],
    validated_at: str,
) -> JudgeValidation:
    """Compara o juiz com anotação humana em uma amostra e devolve kappa.

    `human_labels` é uma lista de {item_id, candidate, label}. O juiz recebe o
    mesmo candidato que o humano viu.
    """
    if len(human_labels) < 30:
        raise DomainError("validação de juiz exige pelo menos 30 itens anotados")
    judge_labels: list[str] = []
    human: list[str] = []
    for record in human_labels:
        item = items.get(str(record["item_id"]))
        if item is None:
            raise DomainError(f"anotação cita item inexistente {record['item_id']!r}")
        label = str(record["label"])
        if label not in JUDGE_LABELS:
            raise DomainError(f"rótulo humano inválido {label!r}")
        verdict = judge.judge(
            question=str(item.input.get("question", "")),
            reference=str(item.expected.get("answer") or "não consta no documento"),
            candidate=str(record["candidate"]),
        )
        judge_labels.append(verdict.label)
        human.append(label)
    kappa = cohens_kappa(judge_labels, human)
    return JudgeValidation(
        judge=judge.identity,
        task=task_name,
        sample_size=len(human_labels),
        kappa=kappa,
        interpretation=interpret_kappa(kappa),
        validated_at=validated_at,
    )


def load_human_labels(path: Path) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    with path.open(encoding="utf-8") as handle:
        for line in handle:
            if line.strip():
                records.append(json.loads(line))
    return records
