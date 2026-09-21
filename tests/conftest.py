from __future__ import annotations

import random
from pathlib import Path

import pytest

from ptbr_benchmark.domain.models import Completion, Item, Observation, Score, ScoringKind, Usage
from ptbr_benchmark.providers.pricing import ModelPrice, PricingTable
from ptbr_benchmark.tasks.base import TaskDefinition
from ptbr_benchmark.tasks.registry import load_tasks

REPO_ROOT = Path(__file__).resolve().parents[1]
TASKS_DIR = REPO_ROOT / "tasks"


@pytest.fixture(scope="session")
def tasks() -> dict[str, TaskDefinition]:
    return {task.name: task for task in load_tasks(TASKS_DIR)}


@pytest.fixture
def rng() -> random.Random:
    return random.Random(1234)


@pytest.fixture
def pricing() -> PricingTable:
    return PricingTable(
        as_of="2026-01-01",
        prices={
            "baseline-rules": ModelPrice(0.0, 0.0),
            "cheap": ModelPrice(1.0, 2.0),
            "expensive": ModelPrice(10.0, 30.0),
        },
    )


def make_completion(text: str, *, model: str = "cheap", latency_ms: float = 10.0) -> Completion:
    return Completion(
        text=text,
        model=model,
        usage=Usage(input_tokens=100, output_tokens=20),
        latency_ms=latency_ms,
    )


def make_observation(
    *,
    item_id: str,
    score: float,
    task: str = "ticket_routing",
    model: str = "cheap",
    prompt_name: str = "minimal",
    repetition: int = 0,
    cost: float = 0.001,
    latency_ms: float = 100.0,
    details: dict[str, object] | None = None,
    estimated: bool = False,
) -> Observation:
    return Observation(
        item_id=item_id,
        task=task,
        provider="test",
        model=model,
        prompt_name=prompt_name,
        prompt_version="abc123",
        repetition=repetition,
        completion=Completion(
            text="{}",
            model=model,
            usage=Usage(input_tokens=10, output_tokens=5, estimated=estimated),
            latency_ms=latency_ms,
        ),
        score=Score(value=score, kind=ScoringKind.CLASSIFICATION, details=details or {}),
        cost_usd=cost,
    )


def make_item(task: str = "ticket_routing", **overrides: object) -> Item:
    base: dict[str, object] = {
        "id": "x-1",
        "task": task,
        "input": {"ticket": "Não consigo entrar, minha senha não funciona"},
        "expected": {"category": "acesso_login"},
    }
    base.update(overrides)
    return Item(**base)  # type: ignore[arg-type]
