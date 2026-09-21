"""Resposta com base em documento interno.

O modelo recebe trechos identificados de um documento e uma pergunta. Precisa
responder citando os IDs dos trechos que sustentam a resposta, ou dizer que a
informação não consta. Citação inexistente zera o item: é a alucinação mais
cara em uso corporativo, porque parece verificável e não é.
"""

from __future__ import annotations

from typing import Any

from ptbr_benchmark.domain.models import DomainError, Item, Score, ScoringKind
from ptbr_benchmark.scoring.normalize import jaccard, normalize_text
from ptbr_benchmark.scoring.scorers import parse_json_object, score_grounded_answer
from ptbr_benchmark.tasks.base import TaskDefinition


class GroundedQaTask(TaskDefinition):
    name = "grounded_qa"
    scoring_kind = ScoringKind.EXACT
    description = "Resposta a pergunta com citação obrigatória de trecho"

    def validate_item(self, item: Item) -> None:
        passages = item.input.get("passages")
        if not isinstance(passages, list) or not passages:
            raise DomainError(f"item {item.id}: sem trechos")
        ids = [passage.get("id") for passage in passages]
        if len(ids) != len(set(ids)) or any(not isinstance(i, str) for i in ids):
            raise DomainError(f"item {item.id}: ids de trecho inválidos ou duplicados")
        if not str(item.input.get("question", "")).strip():
            raise DomainError(f"item {item.id}: sem pergunta")
        expected_ids = item.expected.get("supporting_ids", [])
        if not isinstance(expected_ids, list):
            raise DomainError(f"item {item.id}: supporting_ids precisa ser lista")
        unknown = set(expected_ids) - set(ids)
        if unknown:
            raise DomainError(f"item {item.id}: gabarito cita trecho inexistente {sorted(unknown)}")
        if item.expected.get("answer") is not None and not expected_ids:
            raise DomainError(f"item {item.id}: resposta com gabarito precisa de trecho de apoio")

    def prompt_variables(self, item: Item) -> dict[str, Any]:
        passages = "\n".join(
            f"[{passage['id']}] {passage['text']}" for passage in item.input["passages"]
        )
        return {"passages": passages, "question": item.input["question"]}

    def parse(self, text: str) -> dict[str, Any] | None:
        parsed = parse_json_object(text)
        if parsed is None:
            return None
        citations = parsed.get("citations")
        if citations is None:
            parsed["citations"] = []
        elif isinstance(citations, str):
            parsed["citations"] = [citations]
        elif not isinstance(citations, list):
            return None
        answer = parsed.get("answer")
        if answer is not None and not isinstance(answer, str):
            parsed["answer"] = str(answer)
        return parsed

    def score(self, item: Item, parsed: dict[str, Any] | None) -> Score:
        valid_ids = frozenset(passage["id"] for passage in item.input["passages"])
        expected_ids = frozenset(item.expected.get("supporting_ids", []))
        if parsed is None:
            return Score(value=0.0, kind=ScoringKind.EXACT, details={"parse_error": True})
        return score_grounded_answer(
            expected_answer=item.expected.get("answer"),
            actual_answer=parsed.get("answer"),
            cited_ids=[str(c) for c in parsed.get("citations", [])],
            valid_ids=valid_ids,
            expected_ids=expected_ids,
        )

    def baseline(self, item: Item) -> dict[str, Any]:
        question = str(item.input["question"])
        best_id: str | None = None
        best_text = ""
        best_overlap = 0.0
        question_tokens = set(normalize_text(question).split())
        for passage in item.input["passages"]:
            overlap = jaccard(question, str(passage["text"]))
            passage_tokens = set(normalize_text(str(passage["text"])).split())
            shared = len(question_tokens & passage_tokens)
            if overlap > best_overlap and shared >= 2:
                best_overlap = overlap
                best_id = str(passage["id"])
                best_text = str(passage["text"])
        if best_id is None or best_overlap < 0.08:
            return {"answer": None, "citations": []}
        return {"answer": best_text, "citations": [best_id]}

    def needs_escalation(self, parsed: dict[str, Any] | None) -> bool:
        if parsed is None:
            return True
        return parsed.get("answer") is None and not parsed.get("citations")
