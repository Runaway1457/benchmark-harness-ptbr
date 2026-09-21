"""Contexto de relatório: tudo que os geradores precisam, já agregado."""

from __future__ import annotations

from dataclasses import dataclass

from ptbr_benchmark.domain.metrics import ParetoPoint
from ptbr_benchmark.report.aggregate import ConfigSummary, PromptSensitivity
from ptbr_benchmark.report.gates import PublicationDecision
from ptbr_benchmark.scoring.judge import JudgeValidation


@dataclass(frozen=True, slots=True)
class TaskInfo:
    name: str
    description: str


@dataclass(frozen=True, slots=True)
class ReportContext:
    harness_version: str
    pricing_as_of: str
    latest_run_at: str
    tasks: tuple[TaskInfo, ...]
    summaries: tuple[ConfigSummary, ...]
    points: tuple[ParetoPoint, ...]
    frontier: tuple[ParetoPoint, ...]
    sensitivity: tuple[PromptSensitivity, ...]
    judge_validations: tuple[JudgeValidation, ...]
    dataset_hashes: dict[str, str]
    dataset_sizes: dict[str, int]
    dataset_families: dict[str, int]
    publication: PublicationDecision
    pareto_exclusions: dict[str, tuple[str, ...]]
