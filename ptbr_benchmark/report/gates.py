"""Portões executáveis para transformar resultados em publicação.

Documentação não muda o estado de uma rodada. Somente estes checks, calculados
dos manifestos e observações versionados, podem promover o relatório de
``pre-publication`` para ``published``.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from ptbr_benchmark.domain.models import RunResult
from ptbr_benchmark.providers.pricing import PricingTable
from ptbr_benchmark.report.aggregate import MAX_PUBLISHABLE_ERROR_RATE, ConfigSummary

MIN_MODELS = 2
MIN_PROMPTS = 2
MIN_REPETITIONS = 3
MIN_ITEMS_PER_TASK = 150
_PLACEHOLDERS = frozenset(
    {
        "model",
        "default",
        "your-model",
        "your_exact_model_id",
        "cheap",
        "expensive",
        "test",
    }
)


@dataclass(frozen=True, slots=True)
class GateCheck:
    key: str
    label: str
    passed: bool
    detail: str

    def to_json(self) -> dict[str, object]:
        return {
            "key": self.key,
            "label": self.label,
            "passed": self.passed,
            "detail": self.detail,
        }


@dataclass(frozen=True, slots=True)
class PublicationDecision:
    status: str
    checks: tuple[GateCheck, ...]

    @property
    def passed(self) -> bool:
        return self.status == "published"

    @property
    def failed(self) -> tuple[GateCheck, ...]:
        return tuple(check for check in self.checks if not check.passed)

    def to_json(self) -> dict[str, object]:
        return {
            "status": self.status,
            "passed": self.passed,
            "checks": [check.to_json() for check in self.checks],
        }


def evaluate_publication(
    *,
    runs: tuple[RunResult, ...],
    summaries: tuple[ConfigSummary, ...],
    required_tasks: frozenset[str],
    dataset_sizes: dict[str, int],
    pricing: PricingTable,
) -> PublicationDecision:
    complete_datasets = required_tasks <= dataset_sizes.keys() and all(
        dataset_sizes.get(task, 0) >= MIN_ITEMS_PER_TASK for task in required_tasks
    )
    baseline_summaries = tuple(
        summary for summary in summaries if summary.key.provider == "baseline"
    )
    baseline_tasks = {summary.key.task for summary in baseline_summaries}
    baseline_prompts = {summary.key.prompt_name for summary in baseline_summaries}
    baseline_configurations: dict[tuple[str, str], set[str]] = {}
    for summary in baseline_summaries:
        key = (summary.key.model, summary.key.prompt_name)
        baseline_configurations.setdefault(key, set()).add(summary.key.task)
    calibration_checks = (
        GateCheck(
            "datasets",
            "750 itens públicos",
            complete_datasets,
            f"{sum(dataset_sizes.get(task, 0) for task in required_tasks)} itens em "
            f"{len(required_tasks)} tarefas",
        ),
        GateCheck(
            "baseline",
            "Controle baseline concluído",
            required_tasks <= baseline_tasks,
            f"{len(baseline_tasks & required_tasks)}/{len(required_tasks)} tarefas",
        ),
        GateCheck(
            "baseline_prompts",
            "Duas variantes de prompt no baseline",
            len(baseline_prompts) >= MIN_PROMPTS,
            f"{len(baseline_prompts)} variantes de prompt",
        ),
        GateCheck(
            "baseline_matrix",
            "Cada prompt baseline cobre todas as tarefas",
            bool(baseline_configurations)
            and all(required_tasks <= tasks for tasks in baseline_configurations.values()),
            f"{sum(required_tasks <= tasks for tasks in baseline_configurations.values())}/"
            f"{len(baseline_configurations)} configurações completas",
        ),
        GateCheck(
            "baseline_repetitions",
            "Três observações baseline por item",
            bool(baseline_summaries)
            and all(
                summary.observations >= summary.items * MIN_REPETITIONS
                for summary in baseline_summaries
            ),
            f"mínimo exigido: {MIN_REPETITIONS}",
        ),
        GateCheck(
            "baseline_error_rate",
            "Taxa de erro do baseline em até 2%",
            bool(baseline_summaries)
            and all(
                summary.error_rate <= MAX_PUBLISHABLE_ERROR_RATE for summary in baseline_summaries
            ),
            f"máximo observado: {max((s.error_rate for s in baseline_summaries), default=0.0):.1%}",
        ),
    )
    real_runs = tuple(run for run in runs if is_real_provider(run.spec.provider))
    if not real_runs:
        has_simulation = any(is_simulation_provider(run.spec.provider) for run in runs)
        return PublicationDecision(
            status="simulation" if has_simulation else "calibration",
            checks=calibration_checks,
        )

    real_summaries = tuple(
        summary for summary in summaries if is_real_provider(summary.key.provider)
    )
    model_keys = {(run.spec.provider, run.spec.model) for run in real_runs}
    prompts_by_model: dict[tuple[str, str], set[str]] = {key: set() for key in model_keys}
    for run in real_runs:
        key = (run.spec.provider, run.spec.model)
        prompts_by_model[key].add(run.spec.prompt_name)
    expected_configurations = {
        (run.spec.provider, run.spec.model, run.spec.prompt_name) for run in real_runs
    }

    observed_tasks_by_configuration: dict[tuple[str, str, str], set[str]] = {}
    for summary in real_summaries:
        configuration_key = (
            summary.key.provider,
            summary.key.model,
            summary.key.prompt_name,
        )
        observed_tasks_by_configuration.setdefault(configuration_key, set()).add(summary.key.task)
    complete_configuration_count = sum(
        required_tasks <= observed_tasks_by_configuration.get(configuration, set())
        for configuration in expected_configurations
    )

    exact_ids = all(_models_are_explicit(model) for _provider, model in model_keys)
    priced = all(
        observation.completion.cost_usd is not None
        or pricing.price_for(observation.completion.model) is not None
        for run in real_runs
        for observation in run.observations
    )
    latest_real_date = max(run.finished_at.date() for run in real_runs)
    try:
        pricing_date = date.fromisoformat(pricing.as_of)
    except ValueError:
        pricing_date = date.min

    checks = (
        GateCheck(
            "datasets",
            "750 itens públicos",
            complete_datasets,
            f"{sum(dataset_sizes.get(task, 0) for task in required_tasks)} itens em "
            f"{len(required_tasks)} tarefas",
        ),
        GateCheck(
            "baseline",
            "Controle baseline concluído",
            required_tasks <= baseline_tasks,
            f"{len(baseline_tasks & required_tasks)}/{len(required_tasks)} tarefas",
        ),
        GateCheck(
            "model_matrix",
            "Ao menos duas configurações de modelo real",
            len(model_keys) >= MIN_MODELS,
            f"{len(model_keys)} configurações provedor/modelo distintas",
        ),
        GateCheck(
            "exact_model_ids",
            "IDs exatos dos modelos registrados",
            exact_ids,
            "todos os IDs são explícitos" if exact_ids else "placeholder ou ID de teste detectado",
        ),
        GateCheck(
            "prompt_variants",
            "Duas variantes de prompt por modelo",
            all(len(prompts) >= MIN_PROMPTS for prompts in prompts_by_model.values()),
            "; ".join(
                f"{provider}:{model}={len(prompts)}"
                for (provider, model), prompts in sorted(prompts_by_model.items())
            ),
        ),
        GateCheck(
            "task_matrix",
            "Cada configuração cobre todas as tarefas",
            bool(expected_configurations)
            and all(
                required_tasks <= observed_tasks_by_configuration.get(configuration, set())
                for configuration in expected_configurations
            ),
            f"{complete_configuration_count}/{len(expected_configurations)} "
            "configurações completas",
        ),
        GateCheck(
            "repetitions",
            "Três observações por item",
            bool(real_summaries)
            and all(
                summary.observations >= summary.items * MIN_REPETITIONS
                for summary in real_summaries
            ),
            f"mínimo exigido: {MIN_REPETITIONS}",
        ),
        GateCheck(
            "error_rate",
            "Taxa de erro do provedor em até 2%",
            bool(real_summaries)
            and all(summary.error_rate <= MAX_PUBLISHABLE_ERROR_RATE for summary in real_summaries),
            f"máximo observado: {max((s.error_rate for s in real_summaries), default=0.0):.1%}",
        ),
        GateCheck(
            "pricing",
            "Preço disponível para cada modelo",
            priced,
            f"snapshot de {pricing.as_of}",
        ),
        GateCheck(
            "pricing_freshness",
            "Preços revisados após as execuções",
            pricing_date >= latest_real_date,
            f"preços {pricing.as_of}; execução mais recente {latest_real_date.isoformat()}",
        ),
    )
    return PublicationDecision(
        status="published" if all(check.passed for check in checks) else "pre-publication",
        checks=checks,
    )


def _is_exact_model_id(model: str) -> bool:
    normalized = model.strip().lower()
    return bool(normalized) and normalized not in _PLACEHOLDERS and "your_" not in normalized


def _models_are_explicit(model: str) -> bool:
    """Valida também os dois IDs serializados por uma configuração em cascata."""
    return all(_is_exact_model_id(part) for part in model.split("+"))


def is_real_provider(provider: str) -> bool:
    if provider in {"baseline", "simulation"}:
        return False
    return not (provider.startswith("cascade[baseline:") and "->baseline:" in provider)


def is_simulation_provider(provider: str) -> bool:
    return provider == "simulation" or "simulation:" in provider
