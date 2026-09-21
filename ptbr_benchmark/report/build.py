"""Montagem do relatório a partir do diretório de resultados."""

from __future__ import annotations

import json
from pathlib import Path

from ptbr_benchmark import __version__
from ptbr_benchmark.domain.models import DomainError, Split
from ptbr_benchmark.providers.pricing import PricingTable
from ptbr_benchmark.report.aggregate import (
    all_points,
    overall_pareto,
    paired_prompt_sensitivity,
    read_runs,
    summarize,
)
from ptbr_benchmark.report.context import ReportContext, TaskInfo
from ptbr_benchmark.report.html import render_html
from ptbr_benchmark.report.markdown import render_markdown
from ptbr_benchmark.scoring.judge import JudgeValidation
from ptbr_benchmark.tasks.base import TaskDefinition


def build_context(
    *,
    results_dir: Path,
    tasks: tuple[TaskDefinition, ...],
    pricing: PricingTable,
    seed: int,
) -> ReportContext:
    runs = read_runs(results_dir)
    if not runs:
        raise DomainError(
            f"nenhuma rodada em {results_dir}. Execute `ptbr-benchmark run` primeiro."
        )
    observations = [o for run in runs for o in run.observations]
    summaries = summarize(observations, seed=seed)
    points = all_points(summaries)
    frontier = overall_pareto(summaries)

    dataset_hashes: dict[str, str] = {}
    for run in runs:
        for task_name, digest in run.dataset_hashes.items():
            previous = dataset_hashes.setdefault(task_name, digest)
            if previous != digest:
                raise DomainError(
                    f"rodadas com datasets diferentes para {task_name!r}: "
                    "não é possível agregar. Mova rodadas antigas para outro diretório."
                )
    dataset_sizes = {task.name: len(task.load_items(Split.PUBLIC)) for task in tasks}
    dataset_families = {
        task.name: len({item.scenario_family for item in task.load_items(Split.PUBLIC)})
        for task in tasks
    }

    return ReportContext(
        harness_version=__version__,
        pricing_as_of=pricing.as_of,
        latest_run_at=max(run.finished_at for run in runs).strftime("%Y-%m-%d %H:%M UTC"),
        tasks=tuple(TaskInfo(name=task.name, description=task.description) for task in tasks),
        summaries=summaries,
        points=points,
        frontier=frontier,
        sensitivity=paired_prompt_sensitivity(observations, seed=seed),
        judge_validations=_load_judge_validations(results_dir / "judge_validation"),
        dataset_hashes=dataset_hashes,
        dataset_sizes=dataset_sizes,
        dataset_families=dataset_families,
    )


def _load_judge_validations(directory: Path) -> tuple[JudgeValidation, ...]:
    if not directory.is_dir():
        return ()
    validations: list[JudgeValidation] = []
    for path in sorted(directory.glob("*.json")):
        raw = json.loads(path.read_text(encoding="utf-8"))
        validations.append(
            JudgeValidation(
                judge=str(raw["judge"]),
                task=str(raw["task"]),
                sample_size=int(raw["sample_size"]),
                kappa=float(raw["kappa"]),
                interpretation=str(raw["interpretation"]),
                validated_at=str(raw["validated_at"]),
            )
        )
    return tuple(validations)


def write_reports(
    context: ReportContext, *, docs_dir: Path, site_dir: Path
) -> tuple[Path, Path, Path]:
    docs_dir.mkdir(parents=True, exist_ok=True)
    site_dir.mkdir(parents=True, exist_ok=True)
    markdown_path = docs_dir / "results.md"
    html_path = site_dir / "index.html"
    summary_path = site_dir / "summary.json"
    real_models = sorted(
        {summary.key.model for summary in context.summaries if summary.key.provider != "baseline"}
    )
    markdown_path.write_text(render_markdown(context), encoding="utf-8")
    html_path.write_text(render_html(context), encoding="utf-8")
    summary_path.write_text(
        json.dumps(
            {
                "harness_version": context.harness_version,
                "pricing_as_of": context.pricing_as_of,
                "latest_run_at": context.latest_run_at,
                "publication_status": "published" if real_models else "calibration",
                "real_models": real_models,
                "configurations": [s.to_json() for s in context.summaries],
                "frontier": [p.label for p in context.frontier],
                "dataset_hashes": context.dataset_hashes,
                "dataset_sizes": context.dataset_sizes,
                "dataset_families": context.dataset_families,
                "statistical_unit": "semantic_family",
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    return markdown_path, html_path, summary_path
