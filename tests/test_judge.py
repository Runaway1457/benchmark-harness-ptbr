from __future__ import annotations

import json
from pathlib import Path

import pytest

from ptbr_benchmark.domain.models import DomainError
from ptbr_benchmark.scoring.judge import (
    MINIMUM_KAPPA,
    JudgeValidation,
    LlmJudge,
    Verdict,
    load_human_labels,
    validate_judge,
)
from ptbr_benchmark.tasks.base import TaskDefinition
from tests.conftest import make_completion
from tests.test_providers import ScriptedProvider


def test_verdict_values() -> None:
    assert Verdict("correct", "").value == 1.0
    assert Verdict("partial", "").value == 0.5
    assert Verdict("incorrect", "").value == 0.0
    with pytest.raises(DomainError):
        Verdict("meh", "")


def test_judge_parses_and_falls_back_on_garbage() -> None:
    provider = ScriptedProvider(
        make_completion('{"label": "partial", "rationale": "faltou o prazo"}'),
        make_completion("não sei"),
        make_completion('{"label": "great"}'),
    )
    judge = LlmJudge(provider, model="m")
    assert judge.identity == "scripted:m"
    assert judge.judge(question="q", reference="r", candidate="c").label == "partial"
    assert judge.judge(question="q", reference="r", candidate="c").label == "incorrect"
    assert judge.judge(question="q", reference="r", candidate="c").label == "incorrect"
    assert "Resposta de referência" in provider.calls[0].user


def test_validate_judge_computes_kappa(tasks: dict[str, TaskDefinition], tmp_path: Path) -> None:
    task = tasks["grounded_qa"]
    items = {item.id: item for item in task.load_items()}
    ids = list(items)[:30]
    labels = [
        {"item_id": i, "candidate": "x", "label": "correct" if n % 2 else "incorrect"}
        for n, i in enumerate(ids)
    ]
    path = tmp_path / "labels.jsonl"
    path.write_text("\n".join(json.dumps(r) for r in labels) + "\n\n", encoding="utf-8")
    loaded = load_human_labels(path)
    assert len(loaded) == 30

    perfect = ScriptedProvider(
        *[make_completion(json.dumps({"label": r["label"]})) for r in labels]
    )
    validation = validate_judge(
        LlmJudge(perfect, model="m"),
        task_name=task.name,
        items=items,
        human_labels=loaded,
        validated_at="2026-01-01",
    )
    assert validation.kappa == 1.0
    assert validation.accepted is True
    assert validation.to_json()["minimum_kappa"] == MINIMUM_KAPPA

    always_correct = ScriptedProvider(*[make_completion('{"label": "correct"}')] * 30)
    weak = validate_judge(
        LlmJudge(always_correct, model="m"),
        task_name=task.name,
        items=items,
        human_labels=loaded,
        validated_at="2026-01-01",
    )
    assert weak.kappa == 0.0
    assert weak.accepted is False
    assert weak.interpretation == "insuficiente"


def test_validate_judge_rejects_bad_input(tasks: dict[str, TaskDefinition]) -> None:
    task = tasks["grounded_qa"]
    items = {item.id: item for item in task.load_items()}
    judge = LlmJudge(ScriptedProvider(), model="m")
    with pytest.raises(DomainError, match="30 itens"):
        validate_judge(judge, task_name=task.name, items=items, human_labels=[], validated_at="d")
    bad_item = [{"item_id": "nope", "candidate": "x", "label": "correct"}] * 30
    with pytest.raises(DomainError, match="inexistente"):
        validate_judge(
            judge, task_name=task.name, items=items, human_labels=bad_item, validated_at="d"
        )
    first = next(iter(items))
    bad_label = [{"item_id": first, "candidate": "x", "label": "ok"}] * 30
    with pytest.raises(DomainError, match="rótulo humano"):
        validate_judge(
            judge, task_name=task.name, items=items, human_labels=bad_label, validated_at="d"
        )


def test_judge_validation_threshold() -> None:
    assert JudgeValidation("j", "t", 30, 0.6, "substancial", "d").accepted
    assert not JudgeValidation("j", "t", 30, 0.59, "moderada", "d").accepted
