"""Registro das tarefas disponíveis."""

from __future__ import annotations

from pathlib import Path

from ptbr_benchmark.domain.models import DomainError
from ptbr_benchmark.tasks.base import TaskDefinition
from ptbr_benchmark.tasks.fiscal_extraction import FiscalExtractionTask
from ptbr_benchmark.tasks.grounded_qa import GroundedQaTask
from ptbr_benchmark.tasks.lgpd_refusal import LgpdRefusalTask
from ptbr_benchmark.tasks.regional_ptbr import RegionalPtBrTask
from ptbr_benchmark.tasks.ticket_routing import TicketRoutingTask

TASK_CLASSES: tuple[type[TaskDefinition], ...] = (
    FiscalExtractionTask,
    TicketRoutingTask,
    LgpdRefusalTask,
    GroundedQaTask,
    RegionalPtBrTask,
)

TASK_NAMES: tuple[str, ...] = tuple(cls.name for cls in TASK_CLASSES)


def load_tasks(data_dir: Path, names: tuple[str, ...] | None = None) -> tuple[TaskDefinition, ...]:
    selected = names or TASK_NAMES
    unknown = sorted(set(selected) - set(TASK_NAMES))
    if unknown:
        raise DomainError(f"tarefas desconhecidas: {unknown}. Disponíveis: {list(TASK_NAMES)}")
    by_name = {cls.name: cls for cls in TASK_CLASSES}
    return tuple(by_name[name](data_dir) for name in selected)
