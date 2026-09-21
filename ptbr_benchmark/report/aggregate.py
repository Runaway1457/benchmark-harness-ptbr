"""Persistência de rodadas e agregação para relatório.

Uma rodada é gravada como JSONL de observações mais um manifesto. O relatório
lê todas as rodadas de um diretório e agrega por (tarefa, provedor, modelo,
prompt). Toda média sai com intervalo de confiança; toda configuração sai com
variância entre repetições; o conjunto sai com fronteira de Pareto.
"""

from __future__ import annotations

import gzip
import json
import random
from collections import defaultdict
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from ptbr_benchmark.domain.metrics import (
    Interval,
    ParetoPoint,
    RepetitionSpread,
    bootstrap_mean,
    bootstrap_paired_difference,
    pareto_frontier,
    percentile,
    repetition_spread,
)
from ptbr_benchmark.domain.models import (
    Completion,
    DomainError,
    Observation,
    RunResult,
    RunSpec,
    Score,
    ScoringKind,
    Split,
    Usage,
)


def write_run(result: RunResult, results_dir: Path) -> Path:
    run_dir = results_dir / result.spec.run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    manifest = {
        "run_id": result.spec.run_id,
        "spec": {
            "tasks": list(result.spec.tasks),
            "provider": result.spec.provider,
            "model": result.spec.model,
            "prompt_name": result.spec.prompt_name,
            "repetitions": result.spec.repetitions,
            "seed": result.spec.seed,
            "split": result.spec.split.value,
            "limit": result.spec.limit,
        },
        "started_at": result.started_at.isoformat(),
        "finished_at": result.finished_at.isoformat(),
        "dataset_hashes": result.dataset_hashes,
        "harness_version": result.harness_version,
        "observations": len(result.observations),
        "total_cost_usd": round(result.total_cost_usd, 6),
    }
    (run_dir / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    with (run_dir / "observations.jsonl").open("w", encoding="utf-8") as handle:
        for observation in result.observations:
            handle.write(json.dumps(_observation_to_json(observation), ensure_ascii=False) + "\n")
    return run_dir


def _observation_to_json(observation: Observation) -> dict[str, Any]:
    completion = observation.completion
    return {
        "item_id": observation.item_id,
        "task": observation.task,
        "provider": observation.provider,
        "model": observation.model,
        "prompt_name": observation.prompt_name,
        "prompt_version": observation.prompt_version,
        "repetition": observation.repetition,
        "score": observation.score.value,
        "score_kind": observation.score.kind.value,
        "score_details": observation.score.details,
        "cost_usd": observation.cost_usd,
        "completion": {
            "text": completion.text,
            "model": completion.model,
            "input_tokens": completion.usage.input_tokens,
            "output_tokens": completion.usage.output_tokens,
            "estimated_tokens": completion.usage.estimated,
            "latency_ms": completion.latency_ms,
            "cached": completion.cached,
            "attempts": completion.attempts,
            "error": completion.error,
            "cost_usd": completion.cost_usd,
        },
    }


def read_runs(results_dir: Path) -> tuple[RunResult, ...]:
    runs: list[RunResult] = []
    if not results_dir.is_dir():
        return ()
    for manifest_path in sorted(results_dir.glob("*/manifest.json")):
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        observations_path = manifest_path.with_name("observations.jsonl")
        compressed_path = manifest_path.with_name("observations.jsonl.gz")
        if observations_path.exists():
            observations_text = observations_path.read_text(encoding="utf-8")
        elif compressed_path.exists():
            with gzip.open(compressed_path, mode="rt", encoding="utf-8") as handle:
                observations_text = handle.read()
        else:
            raise DomainError(f"rodada sem observações: {manifest_path.parent}")
        spec_raw = manifest["spec"]
        spec = RunSpec(
            tasks=tuple(spec_raw["tasks"]),
            provider=spec_raw["provider"],
            model=spec_raw["model"],
            prompt_name=spec_raw["prompt_name"],
            repetitions=int(spec_raw["repetitions"]),
            seed=int(spec_raw["seed"]),
            split=Split(spec_raw["split"]),
            limit=spec_raw.get("limit"),
        )
        observations = tuple(
            _observation_from_json(json.loads(line))
            for line in observations_text.splitlines()
            if line.strip()
        )
        runs.append(
            RunResult(
                spec=spec,
                started_at=datetime.fromisoformat(manifest["started_at"]),
                finished_at=datetime.fromisoformat(manifest["finished_at"]),
                observations=observations,
                dataset_hashes=dict(manifest["dataset_hashes"]),
                harness_version=str(manifest["harness_version"]),
            )
        )
    return tuple(runs)


def _observation_from_json(raw: dict[str, Any]) -> Observation:
    completion_raw = raw["completion"]
    return Observation(
        item_id=raw["item_id"],
        task=raw["task"],
        provider=raw["provider"],
        model=raw["model"],
        prompt_name=raw["prompt_name"],
        prompt_version=raw["prompt_version"],
        repetition=int(raw["repetition"]),
        completion=Completion(
            text=completion_raw["text"],
            model=completion_raw["model"],
            usage=Usage(
                input_tokens=int(completion_raw["input_tokens"]),
                output_tokens=int(completion_raw["output_tokens"]),
                estimated=bool(completion_raw.get("estimated_tokens", False)),
            ),
            latency_ms=float(completion_raw["latency_ms"]),
            cached=bool(completion_raw.get("cached", False)),
            attempts=int(completion_raw.get("attempts", 1)),
            error=completion_raw.get("error"),
            cost_usd=completion_raw.get("cost_usd"),
        ),
        score=Score(
            value=float(raw["score"]),
            kind=ScoringKind(raw["score_kind"]),
            details=dict(raw.get("score_details", {})),
        ),
        cost_usd=float(raw["cost_usd"]),
    )


@dataclass(frozen=True, slots=True)
class ConfigKey:
    task: str
    provider: str
    model: str
    prompt_name: str

    @property
    def label(self) -> str:
        return f"{self.model} / {self.prompt_name}"


@dataclass(frozen=True, slots=True)
class ConfigSummary:
    key: ConfigKey
    quality: Interval
    cost_per_item_usd: float
    cost_estimated: bool
    latency_p50_ms: float
    latency_p95_ms: float
    spread: RepetitionSpread
    items: int
    observations: int
    error_rate: float
    cache_hit_rate: float
    extra: dict[str, Any]

    def to_json(self) -> dict[str, Any]:
        return {
            "task": self.key.task,
            "provider": self.key.provider,
            "model": self.key.model,
            "prompt": self.key.prompt_name,
            "quality": {
                "mean": round(self.quality.point, 4),
                "ci_lower": round(self.quality.lower, 4),
                "ci_upper": round(self.quality.upper, 4),
            },
            "cost_per_item_usd": round(self.cost_per_item_usd, 6),
            "cost_estimated": self.cost_estimated,
            "latency_p50_ms": round(self.latency_p50_ms, 1),
            "latency_p95_ms": round(self.latency_p95_ms, 1),
            "repetition_disagreement_rate": round(self.spread.disagreement_rate, 4),
            "repetition_mean_std": round(self.spread.mean_within_item_std, 4),
            "items": self.items,
            "observations": self.observations,
            "error_rate": round(self.error_rate, 4),
            "cache_hit_rate": round(self.cache_hit_rate, 4),
            "extra": self.extra,
        }


def summarize(observations: Iterable[Observation], *, seed: int) -> tuple[ConfigSummary, ...]:
    grouped: dict[ConfigKey, list[Observation]] = defaultdict(list)
    for observation in observations:
        key = ConfigKey(
            task=observation.task,
            provider=observation.provider,
            model=observation.model,
            prompt_name=observation.prompt_name,
        )
        grouped[key].append(observation)

    summaries: list[ConfigSummary] = []
    for key, group in sorted(
        grouped.items(), key=lambda pair: (pair[0].task, pair[0].model, pair[0].prompt_name)
    ):
        per_item_mean = _mean_per_item(group)
        per_family_mean = _mean_per_family(group)
        has_classification_labels = all(
            "expected" in observation.score.details and "actual" in observation.score.details
            for observation in group
        )
        quality = (
            _bootstrap_macro_f1(group, seed=seed)
            if key.task == "ticket_routing" and has_classification_labels
            else bootstrap_mean(list(per_family_mean.values()), seed=seed)
        )
        latencies = [o.completion.latency_ms for o in group if o.completion.error is None]
        summaries.append(
            ConfigSummary(
                key=key,
                quality=quality,
                # Repetitions estimate stochastic variance. They must not
                # multiply the published unit economics.
                cost_per_item_usd=sum(o.cost_usd for o in group) / len(group),
                cost_estimated=any(o.completion.usage.estimated for o in group),
                latency_p50_ms=percentile(latencies, 50) if latencies else 0.0,
                latency_p95_ms=percentile(latencies, 95) if latencies else 0.0,
                spread=repetition_spread(group),
                items=len(per_item_mean),
                observations=len(group),
                error_rate=sum(1 for o in group if o.completion.error) / len(group),
                cache_hit_rate=sum(1 for o in group if o.completion.cached) / len(group),
                extra=_task_specific(key.task, group),
            )
        )
    return tuple(summaries)


def _classification_metrics(details: Iterable[dict[str, Any]]) -> dict[str, Any]:
    rows = [item for item in details if item.get("expected")]
    labels = sorted({str(item["expected"]) for item in rows})
    per_label: dict[str, float] = {}
    for label in labels:
        true_positive = sum(
            1 for item in rows if item.get("expected") == label and item.get("actual") == label
        )
        false_positive = sum(
            1 for item in rows if item.get("expected") != label and item.get("actual") == label
        )
        false_negative = sum(
            1 for item in rows if item.get("expected") == label and item.get("actual") != label
        )
        denominator = 2 * true_positive + false_positive + false_negative
        per_label[label] = (2 * true_positive / denominator) if denominator else 0.0
    macro = sum(per_label.values()) / len(per_label) if per_label else 0.0
    accuracy = (
        sum(1 for item in rows if item.get("expected") == item.get("actual")) / len(rows)
        if rows
        else 0.0
    )
    return {
        "macro_f1": macro,
        "accuracy": accuracy,
        "per_label_f1": per_label,
    }


def _bootstrap_macro_f1(group: list[Observation], *, seed: int, resamples: int = 2000) -> Interval:
    by_item: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for observation in group:
        by_item[observation.item_id].append(observation.score.details)
    by_family: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for item_id, details in by_item.items():
        by_family[_scenario_family(item_id)].extend(details)
    family_ids = sorted(by_family)
    point = float(_classification_metrics(o.score.details for o in group)["macro_f1"])
    if len(family_ids) == 1:
        return Interval(point=point, lower=point, upper=point, n=1)
    rng = random.Random(seed)
    samples: list[float] = []
    for _ in range(resamples):
        sampled = rng.choices(family_ids, k=len(family_ids))
        details = [detail for family_id in sampled for detail in by_family[family_id]]
        samples.append(float(_classification_metrics(details)["macro_f1"]))
    ordered = sorted(samples)
    lower = ordered[int(0.025 * resamples)]
    upper = ordered[min(int(0.975 * resamples), resamples - 1)]
    return Interval(
        point=point,
        lower=min(lower, point),
        upper=max(upper, point),
        n=len(family_ids),
    )


def _mean_per_item(group: Iterable[Observation]) -> dict[str, float]:
    by_item: dict[str, list[float]] = defaultdict(list)
    for observation in group:
        by_item[observation.item_id].append(observation.score.value)
    return {item_id: sum(values) / len(values) for item_id, values in by_item.items()}


def _scenario_family(item_id: str) -> str:
    return item_id.split("--", 1)[0]


def _mean_per_family(group: Iterable[Observation]) -> dict[str, float]:
    per_item = _mean_per_item(group)
    by_family: dict[str, list[float]] = defaultdict(list)
    for item_id, value in per_item.items():
        by_family[_scenario_family(item_id)].append(value)
    return {family: sum(values) / len(values) for family, values in by_family.items()}


def _task_specific(task: str, group: list[Observation]) -> dict[str, Any]:
    details = [o.score.details for o in group]
    if task == "lgpd_refusal":
        n = len(details)
        return {
            "leak_rate": round(sum(1 for d in details if d.get("leak")) / n, 4),
            "over_refusal_rate": round(sum(1 for d in details if d.get("over_refusal")) / n, 4),
        }
    if task == "grounded_qa":
        n = len(details)
        return {
            "invented_citation_rate": round(
                sum(1 for d in details if d.get("invented_citations")) / n, 4
            ),
            "hallucinated_answer_rate": round(
                sum(1 for d in details if d.get("hallucinated_answer")) / n, 4
            ),
        }
    if task == "fiscal_extraction":
        field_hits: dict[str, list[bool]] = defaultdict(list)
        parse_errors = 0
        for detail in details:
            if detail.get("parse_error"):
                parse_errors += 1
                continue
            for field_name, ok in detail.get("fields", {}).items():
                field_hits[field_name].append(bool(ok))
        return {
            "parse_error_rate": round(parse_errors / len(details), 4),
            "field_accuracy": {
                name: round(sum(hits) / len(hits), 4) for name, hits in sorted(field_hits.items())
            },
            "all_fields_correct_rate": round(
                sum(1 for d in details if d.get("all_correct")) / len(details), 4
            ),
        }
    if task == "ticket_routing":
        n = len(details)
        metrics = _classification_metrics(details)
        return {
            "invalid_label_rate": round(
                sum(1 for d in details if not d.get("valid_label", True)) / n, 4
            ),
            "macro_f1": round(float(metrics["macro_f1"]), 4),
            "accuracy": round(float(metrics["accuracy"]), 4),
            "per_label_f1": {
                str(name): round(float(value), 4)
                for name, value in dict(metrics["per_label_f1"]).items()
            },
        }
    if task == "regional_ptbr":
        n = len(details)
        return {
            "invalid_answer_rate": round(sum(1 for d in details if not d.get("valid", True)) / n, 4)
        }
    return {}


@dataclass(frozen=True, slots=True)
class PromptSensitivity:
    task: str
    model: str
    prompt_a: str
    prompt_b: str
    quality_a: Interval
    quality_b: Interval
    paired_delta: Interval | None = None

    @property
    def delta(self) -> float:
        if self.paired_delta is not None:
            return self.paired_delta.point
        return self.quality_b.point - self.quality_a.point

    @property
    def significant(self) -> bool:
        if self.paired_delta is not None:
            return self.paired_delta.lower > 0 or self.paired_delta.upper < 0
        return not self.quality_a.overlaps(self.quality_b)


def prompt_sensitivity(summaries: Iterable[ConfigSummary]) -> tuple[PromptSensitivity, ...]:
    """Para cada (tarefa, modelo) com dois ou mais prompts, compara o primeiro com cada outro."""
    grouped: dict[tuple[str, str], list[ConfigSummary]] = defaultdict(list)
    for summary in summaries:
        grouped[(summary.key.task, summary.key.model)].append(summary)
    comparisons: list[PromptSensitivity] = []
    for (task, model), configs in sorted(grouped.items()):
        if len(configs) < 2:
            continue
        ordered = sorted(configs, key=lambda c: c.key.prompt_name)
        base = ordered[0]
        for other in ordered[1:]:
            comparisons.append(
                PromptSensitivity(
                    task=task,
                    model=model,
                    prompt_a=base.key.prompt_name,
                    prompt_b=other.key.prompt_name,
                    quality_a=base.quality,
                    quality_b=other.quality,
                )
            )
    return tuple(comparisons)


def paired_prompt_sensitivity(
    observations: Iterable[Observation], *, seed: int
) -> tuple[PromptSensitivity, ...]:
    """Compara prompts no mesmo conjunto de itens via bootstrap pareado."""
    grouped: dict[tuple[str, str, str], dict[str, list[Observation]]] = defaultdict(
        lambda: defaultdict(list)
    )
    for observation in observations:
        grouped[(observation.task, observation.provider, observation.model)][
            observation.prompt_name
        ].append(observation)

    comparisons: list[PromptSensitivity] = []
    for (task, _provider, model), by_prompt in sorted(grouped.items()):
        if len(by_prompt) < 2:
            continue
        prompt_names = sorted(by_prompt)
        base_name = prompt_names[0]
        base_means = _mean_per_family(by_prompt[base_name])
        quality_a = bootstrap_mean(list(base_means.values()), seed=seed)
        for prompt_name in prompt_names[1:]:
            other_means = _mean_per_family(by_prompt[prompt_name])
            common = sorted(set(base_means) & set(other_means))
            if not common:
                continue
            pairs = [(base_means[item], other_means[item]) for item in common]
            quality_b = bootstrap_mean(list(other_means.values()), seed=seed)
            comparisons.append(
                PromptSensitivity(
                    task=task,
                    model=model,
                    prompt_a=base_name,
                    prompt_b=prompt_name,
                    quality_a=quality_a,
                    quality_b=quality_b,
                    paired_delta=bootstrap_paired_difference(pairs, seed=seed),
                )
            )
    return tuple(comparisons)


def overall_pareto(summaries: Iterable[ConfigSummary]) -> tuple[ParetoPoint, ...]:
    """Um ponto por (modelo, prompt), com qualidade média entre tarefas e custo somado."""
    grouped: dict[tuple[str, str], list[ConfigSummary]] = defaultdict(list)
    for summary in summaries:
        grouped[(summary.key.model, summary.key.prompt_name)].append(summary)
    return pareto_frontier(_points_from(grouped))


def all_points(summaries: Iterable[ConfigSummary]) -> tuple[ParetoPoint, ...]:
    grouped: dict[tuple[str, str], list[ConfigSummary]] = defaultdict(list)
    for summary in summaries:
        grouped[(summary.key.model, summary.key.prompt_name)].append(summary)
    return _points_from(grouped)


def _points_from(grouped: dict[tuple[str, str], list[ConfigSummary]]) -> tuple[ParetoPoint, ...]:
    """Arredonda custo e latência antes de comparar, para que ruído de microssegundo
    não decida quem está na fronteira."""
    return tuple(
        ParetoPoint(
            label=f"{model} / {prompt}",
            quality=round(sum(c.quality.point for c in configs) / len(configs), 4),
            cost_per_item_usd=round(sum(c.cost_per_item_usd for c in configs) / len(configs), 6),
            latency_p95_ms=round(max(c.latency_p95_ms for c in configs)),
        )
        for (model, prompt), configs in sorted(grouped.items())
    )
