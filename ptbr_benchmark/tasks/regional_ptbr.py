"""Compreensão de português brasileiro regional.

Uma frase com expressão regional, quatro interpretações, uma correta. O
formato de múltipla escolha mantém a pontuação exata e evita juiz. Cobre
Nordeste, Sul, Norte, Sudeste interior e Centro-Oeste, com tag de região
para o relatório quebrar acurácia por variante.
"""

from __future__ import annotations

from typing import Any

from ptbr_benchmark.domain.models import DomainError, Item, Score, ScoringKind
from ptbr_benchmark.scoring.normalize import jaccard
from ptbr_benchmark.scoring.scorers import parse_json_object, score_choice
from ptbr_benchmark.tasks.base import TaskDefinition

REGIONS: frozenset[str] = frozenset(
    {"nordeste", "sul", "norte", "sudeste_interior", "centro_oeste", "sudeste_capital"}
)
_LETTERS = ("A", "B", "C", "D")


class RegionalPtBrTask(TaskDefinition):
    name = "regional_ptbr"
    scoring_kind = ScoringKind.EXACT
    description = "Interpretação de expressão regional em múltipla escolha"

    def validate_item(self, item: Item) -> None:
        options = item.input.get("options")
        if not isinstance(options, list) or len(options) != 4:
            raise DomainError(f"item {item.id}: exige exatamente 4 opções")
        if len({str(o).strip().lower() for o in options}) != 4:
            raise DomainError(f"item {item.id}: opções repetidas")
        if item.expected.get("answer") not in _LETTERS:
            raise DomainError(f"item {item.id}: gabarito fora de A-D")
        if item.input.get("region") not in REGIONS:
            raise DomainError(f"item {item.id}: região {item.input.get('region')!r} desconhecida")
        if not str(item.input.get("sentence", "")).strip():
            raise DomainError(f"item {item.id}: sem frase")

    def prompt_variables(self, item: Item) -> dict[str, Any]:
        options = "\n".join(
            f"{letter}) {option}"
            for letter, option in zip(_LETTERS, item.input["options"], strict=True)
        )
        return {"sentence": item.input["sentence"], "options": options}

    def parse(self, text: str) -> dict[str, Any] | None:
        parsed = parse_json_object(text)
        if parsed is not None and "answer" in parsed:
            return {"answer": str(parsed["answer"])}
        stripped = text.strip()
        if (
            stripped
            and stripped[0].upper() in _LETTERS
            and (len(stripped) == 1 or not stripped[1].isalnum())
        ):
            return {"answer": stripped[0].upper()}
        return None

    def score(self, item: Item, parsed: dict[str, Any] | None) -> Score:
        actual = parsed.get("answer") if parsed else None
        return score_choice(
            str(item.expected["answer"]),
            actual,
            options=tuple(str(o) for o in item.input["options"]),
        )

    def baseline(self, item: Item) -> dict[str, Any]:
        sentence = str(item.input["sentence"])
        ranked = sorted(
            zip(_LETTERS, item.input["options"], strict=True),
            key=lambda pair: jaccard(sentence, str(pair[1])),
            reverse=True,
        )
        return {"answer": ranked[0][0]}
