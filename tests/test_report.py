from __future__ import annotations

import gzip
import hashlib
import json
from dataclasses import replace
from pathlib import Path

import pytest

from ptbr_benchmark.domain.metrics import Interval, ParetoPoint
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
    utc_now,
)
from ptbr_benchmark.providers.pricing import ModelPrice, PricingTable
from ptbr_benchmark.report.aggregate import (
    all_points,
    overall_pareto,
    paired_prompt_sensitivity,
    prompt_sensitivity,
    read_runs,
    summarize,
    write_run,
)
from ptbr_benchmark.report.build import build_context, write_reports
from ptbr_benchmark.report.context import ReportContext, TaskInfo
from ptbr_benchmark.report.gates import PublicationDecision, evaluate_publication
from ptbr_benchmark.report.html import render_html
from ptbr_benchmark.report.markdown import render_markdown
from ptbr_benchmark.scoring.judge import JudgeValidation
from ptbr_benchmark.tasks.base import TaskDefinition
from tests.conftest import make_observation


def _run(observations: list, *, tasks: tuple[str, ...], model: str, prompt: str) -> RunResult:
    spec = RunSpec(tasks, "test", model, prompt, 2, 42, Split.PUBLIC)
    now = utc_now()
    return RunResult(spec, now, now, tuple(observations), {t: "h" for t in tasks}, "0.1.0")


class TestPersistence:
    def test_write_and_read_roundtrip(self, tmp_path: Path) -> None:
        observations = [
            make_observation(item_id="a", score=1.0, repetition=0, details={"valid_label": True}),
            make_observation(item_id="a", score=0.0, repetition=1, details={"valid_label": False}),
        ]
        result = _run(observations, tasks=("ticket_routing",), model="cheap", prompt="minimal")
        run_dir = write_run(result, tmp_path)
        assert (run_dir / "manifest.json").exists()
        manifest = json.loads((run_dir / "manifest.json").read_text())
        assert manifest["observations"] == 2
        assert manifest["spec"]["split"] == "public"

        runs = read_runs(tmp_path)
        assert len(runs) == 1
        assert runs[0].spec == result.spec
        assert runs[0].observations == result.observations

    def test_read_run_from_deterministic_gzip_artifact(self, tmp_path: Path) -> None:
        result = _run(
            [make_observation(item_id="a", score=1.0)],
            tasks=("ticket_routing",),
            model="cheap",
            prompt="minimal",
        )
        run_dir = write_run(result, tmp_path)
        source = run_dir / "observations.jsonl"
        compressed = run_dir / "observations.jsonl.gz"
        with (
            source.open("rb") as source_handle,
            compressed.open("wb") as target_handle,
            gzip.GzipFile(fileobj=target_handle, mode="wb", mtime=0) as gzip_handle,
        ):
            gzip_handle.write(source_handle.read())
        source.unlink()

        runs = read_runs(tmp_path)
        assert len(runs) == 1
        assert runs[0].observations == result.observations

    def test_read_empty_and_broken(self, tmp_path: Path) -> None:
        assert read_runs(tmp_path / "nope") == ()
        broken = tmp_path / "run"
        broken.mkdir()
        (broken / "manifest.json").write_text("{}")
        with pytest.raises(DomainError, match="sem observações"):
            read_runs(tmp_path)


class TestSummarize:
    def test_groups_by_config_and_computes_rates(self) -> None:
        observations = [
            make_observation(item_id="a", score=1.0, repetition=0, latency_ms=100),
            make_observation(item_id="a", score=0.0, repetition=1, latency_ms=300),
            make_observation(item_id="b", score=1.0, repetition=0, latency_ms=200),
            make_observation(item_id="b", score=1.0, repetition=1, latency_ms=400, estimated=True),
            make_observation(item_id="a", score=0.5, model="expensive", cost=0.01),
        ]
        summaries = summarize(observations, seed=1)
        assert len(summaries) == 2
        cheap = next(s for s in summaries if s.key.model == "cheap")
        assert cheap.items == 2 and cheap.observations == 4
        assert cheap.quality.point == pytest.approx(0.75)
        assert cheap.cost_estimated is True
        assert cheap.spread.items_with_disagreement == 1
        assert cheap.latency_p50_ms == 250.0
        assert cheap.cost_per_item_usd == pytest.approx(0.004 / 4)
        assert cheap.to_json()["items"] == 2

    def test_task_specific_extras(self) -> None:
        lgpd = summarize(
            [
                make_observation(
                    item_id="a", score=0.0, task="lgpd_refusal", details={"leak": True}
                ),
                make_observation(
                    item_id="b", score=0.0, task="lgpd_refusal", details={"over_refusal": True}
                ),
                make_observation(item_id="c", score=1.0, task="lgpd_refusal", details={}),
            ],
            seed=1,
        )[0]
        assert lgpd.extra == {"leak_rate": 0.3333, "over_refusal_rate": 0.3333}

        gqa = summarize(
            [
                make_observation(
                    item_id="a",
                    score=0.0,
                    task="grounded_qa",
                    details={"invented_citations": ["p9"]},
                ),
                make_observation(
                    item_id="b",
                    score=0.0,
                    task="grounded_qa",
                    details={"hallucinated_answer": True},
                ),
            ],
            seed=1,
        )[0]
        assert gqa.extra["invented_citation_rate"] == 0.5
        assert gqa.extra["hallucinated_answer_rate"] == 0.5

        fiscal = summarize(
            [
                make_observation(
                    item_id="a",
                    score=1.0,
                    task="fiscal_extraction",
                    details={"fields": {"cnpj": True, "total": True}, "all_correct": True},
                ),
                make_observation(
                    item_id="b",
                    score=0.5,
                    task="fiscal_extraction",
                    details={"fields": {"cnpj": False, "total": True}, "all_correct": False},
                ),
                make_observation(
                    item_id="c", score=0.0, task="fiscal_extraction", details={"parse_error": True}
                ),
            ],
            seed=1,
        )[0]
        assert fiscal.extra["parse_error_rate"] == 0.3333
        assert fiscal.extra["field_accuracy"] == {"cnpj": 0.5, "total": 1.0}
        assert fiscal.extra["all_fields_correct_rate"] == 0.3333

        ticket = summarize(
            [
                make_observation(
                    item_id="a", score=0.0, task="ticket_routing", details={"valid_label": False}
                )
            ],
            seed=1,
        )[0]
        assert ticket.extra["invalid_label_rate"] == 1.0
        assert ticket.extra["macro_f1"] == 0.0
        assert ticket.extra["accuracy"] == 0.0
        regional = summarize(
            [
                make_observation(
                    item_id="a", score=0.0, task="regional_ptbr", details={"valid": False}
                )
            ],
            seed=1,
        )[0]
        assert regional.extra == {"invalid_answer_rate": 1.0}
        other = summarize([make_observation(item_id="a", score=1.0, task="outra")], seed=1)[0]
        assert other.extra == {}

    def test_error_observations_excluded_from_latency(self) -> None:
        errored = Observation(
            item_id="a",
            task="ticket_routing",
            provider="test",
            model="cheap",
            prompt_name="minimal",
            prompt_version="v",
            repetition=0,
            completion=Completion(
                text="",
                model="cheap",
                usage=Usage(0, 0, estimated=True),
                latency_ms=0.0,
                error="boom",
            ),
            score=Score(value=0.0, kind=ScoringKind.CLASSIFICATION, details={}),
            cost_usd=0.0,
        )
        summary = summarize([errored], seed=1)[0]
        assert summary.error_rate == 1.0
        assert summary.latency_p95_ms == 0.0

    def test_surface_variants_are_clustered_by_semantic_family(self) -> None:
        observations = [
            make_observation(item_id="family-a", score=1.0),
            make_observation(item_id="family-a--formal", score=1.0),
            make_observation(item_id="family-a--noisy", score=1.0),
            make_observation(item_id="family-b", score=0.0),
        ]
        summary = summarize(observations, seed=1)[0]
        assert summary.items == 4
        assert summary.quality.point == pytest.approx(0.5)
        assert summary.quality.n == 2

    def test_ticket_quality_is_macro_f1_not_accuracy(self) -> None:
        observations = [
            make_observation(
                item_id=f"majority-{index}",
                score=1.0,
                task="ticket_routing",
                details={"expected": "A", "actual": "A", "valid_label": True},
            )
            for index in range(9)
        ]
        observations.append(
            make_observation(
                item_id="minority-1",
                score=0.0,
                task="ticket_routing",
                details={"expected": "B", "actual": "A", "valid_label": True},
            )
        )
        summary = summarize(observations, seed=1)[0]
        assert summary.extra["accuracy"] == 0.9
        assert summary.quality.point == pytest.approx(summary.extra["macro_f1"], abs=1e-4)
        assert summary.quality.point < 0.5


class TestSensitivityAndPareto:
    def test_prompt_sensitivity_pairs_first_with_others(self) -> None:
        observations = [
            *(
                make_observation(item_id=f"i{i}", score=0.2, prompt_name="minimal")
                for i in range(30)
            ),
            *(
                make_observation(item_id=f"i{i}", score=0.9, prompt_name="optimized")
                for i in range(30)
            ),
            *(
                make_observation(
                    item_id=f"i{i}", score=0.9, prompt_name="minimal", model="expensive"
                )
                for i in range(5)
            ),
        ]
        comparisons = prompt_sensitivity(summarize(observations, seed=1))
        assert len(comparisons) == 1
        comparison = comparisons[0]
        assert (comparison.prompt_a, comparison.prompt_b) == ("minimal", "optimized")
        assert comparison.delta == pytest.approx(0.7)
        assert comparison.significant is True

        paired = paired_prompt_sensitivity(observations, seed=1)
        assert len(paired) == 1
        assert paired[0].paired_delta is not None
        assert paired[0].paired_delta.lower > 0
        assert paired[0].significant is True

    def test_paired_prompt_sensitivity_clusters_surface_variants(self) -> None:
        observations = [
            make_observation(item_id="a", score=0.0, prompt_name="minimal"),
            make_observation(item_id="a--formal", score=0.0, prompt_name="minimal"),
            make_observation(item_id="b", score=1.0, prompt_name="minimal"),
            make_observation(item_id="a", score=1.0, prompt_name="optimized"),
            make_observation(item_id="a--formal", score=1.0, prompt_name="optimized"),
            make_observation(item_id="b", score=1.0, prompt_name="optimized"),
        ]
        comparison = paired_prompt_sensitivity(observations, seed=4)[0]
        assert comparison.paired_delta is not None
        assert comparison.paired_delta.n == 2
        assert comparison.delta == pytest.approx(0.5)

    def test_pareto_aggregates_across_tasks_and_rounds(self) -> None:
        observations = [
            make_observation(
                item_id="a", score=1.0, task="t1", model="cheap", cost=0.001, latency_ms=100.4
            ),
            make_observation(
                item_id="a", score=0.5, task="t2", model="cheap", cost=0.001, latency_ms=100.2
            ),
            make_observation(
                item_id="a", score=1.0, task="t1", model="expensive", cost=0.01, latency_ms=900
            ),
            make_observation(
                item_id="a", score=0.5, task="t2", model="expensive", cost=0.01, latency_ms=900
            ),
        ]
        summaries = summarize(observations, seed=1)
        points = all_points(summaries)
        assert len(points) == 2
        cheap = next(p for p in points if p.label.startswith("cheap"))
        assert cheap.quality == 0.75
        assert cheap.latency_p95_ms == 100
        frontier = overall_pareto(summaries)
        assert [p.label for p in frontier] == ["cheap / minimal"]

    def test_failed_configuration_never_enters_decision_surface(self) -> None:
        failed = Observation(
            item_id="a",
            task="ticket_routing",
            provider="openai",
            model="broken-model",
            prompt_name="optimized",
            prompt_version="v",
            repetition=0,
            completion=Completion(
                text="",
                model="broken-model",
                usage=Usage(0, 0, estimated=True),
                latency_ms=0.0,
                error="HTTP 400: unsupported parameter",
            ),
            score=Score(0.0, ScoringKind.CLASSIFICATION, {}),
            cost_usd=0.0,
        )
        summaries = summarize([failed], seed=1)
        assert all_points(summaries) == ()
        assert overall_pareto(summaries) == ()

    def test_ticket_prompt_sensitivity_uses_macro_f1_everywhere(self) -> None:
        observations = []
        for prompt, minority_prediction in (("minimal", "A"), ("optimized", "B")):
            observations.extend(
                make_observation(
                    item_id=f"majority-{index}",
                    score=1.0,
                    task="ticket_routing",
                    prompt_name=prompt,
                    details={"expected": "A", "actual": "A", "valid_label": True},
                )
                for index in range(9)
            )
            observations.append(
                make_observation(
                    item_id="minority",
                    score=1.0 if minority_prediction == "B" else 0.0,
                    task="ticket_routing",
                    prompt_name=prompt,
                    details={
                        "expected": "B",
                        "actual": minority_prediction,
                        "valid_label": True,
                    },
                )
            )
        summaries = summarize(observations, seed=1)
        comparison = paired_prompt_sensitivity(observations, seed=1)[0]
        expected = {summary.key.prompt_name: summary.quality.point for summary in summaries}
        assert comparison.quality_a.point == pytest.approx(expected["minimal"])
        assert comparison.quality_b.point == pytest.approx(expected["optimized"])
        assert comparison.delta > 0


def _context(**overrides: object) -> ReportContext:
    summaries = summarize(
        [
            make_observation(
                item_id="a", score=1.0, task="ticket_routing", details={"valid_label": True}
            ),
            make_observation(
                item_id="b", score=0.0, task="ticket_routing", details={"valid_label": True}
            ),
            make_observation(
                item_id="a",
                score=1.0,
                task="ticket_routing",
                prompt_name="optimized",
                estimated=True,
            ),
            make_observation(item_id="a", score=0.5, task="lgpd_refusal", details={"leak": True}),
            make_observation(
                item_id="a", score=0.5, task="grounded_qa", details={"invented_citations": ["x"]}
            ),
            make_observation(
                item_id="a",
                score=0.5,
                task="fiscal_extraction",
                details={"fields": {"cnpj": True}, "all_correct": True},
            ),
        ],
        seed=1,
    )
    base: dict[str, object] = {
        "harness_version": "0.1.0",
        "pricing_as_of": "2026-01-01",
        "latest_run_at": "2026-01-02 10:00 UTC",
        "tasks": (
            TaskInfo("fiscal_extraction", "Extração"),
            TaskInfo("ticket_routing", "Roteamento"),
            TaskInfo("lgpd_refusal", "LGPD"),
            TaskInfo("grounded_qa", "QA"),
            TaskInfo("regional_ptbr", "Regional"),
        ),
        "summaries": summaries,
        "points": all_points(summaries),
        "frontier": overall_pareto(summaries),
        "sensitivity": prompt_sensitivity(summaries),
        "judge_validations": (),
        "dataset_hashes": {"ticket_routing": "abcdef0123456789xyz"},
        "dataset_sizes": {"ticket_routing": 150},
        "dataset_families": {"ticket_routing": 48},
        "publication": PublicationDecision(status="pre-publication", checks=()),
        "pareto_exclusions": {},
    }
    base.update(overrides)
    return ReportContext(**base)  # type: ignore[arg-type]


class TestRenderers:
    def test_markdown_and_html_are_deterministic(self) -> None:
        context = _context()
        md_a, md_b = render_markdown(context), render_markdown(context)
        html_a, html_b = render_html(context), render_html(context)
        assert (
            hashlib.sha256(md_a.encode()).hexdigest() == hashlib.sha256(md_b.encode()).hexdigest()
        )
        assert (
            hashlib.sha256(html_a.encode()).hexdigest()
            == hashlib.sha256(html_b.encode()).hexdigest()
        )

    def test_markdown_sections(self) -> None:
        text = render_markdown(_context())
        assert "# Resultados" in text
        assert "## Fronteira de Pareto" in text
        assert "## ticket_routing" in text
        assert "## Sensibilidade a prompt" in text
        assert "Nenhum juiz automático" in text
        assert "`abcdef0123456789`" in text
        assert "~$" in text
        assert "Vazamento" in text and "Citação inventada" in text and "Acurácia por campo" in text

    def test_html_is_self_contained_and_escaped(self) -> None:
        context = _context(dataset_hashes={"ticket_routing": "<script>alert(1)</script>"})
        page = render_html(context)
        assert page.startswith("<!doctype html>")
        assert page.count("<script>") == 1
        assert "<script>alert(1)</script>" not in page
        assert "&lt;script&gt;" in page
        assert 'lang="pt-BR"' in page
        assert "http://" not in page and "https://" not in page
        assert "<svg" in page and "Custo por item (USD)" in page
        assert 'class="frontier"' in page
        assert "Sensibilidade a prompt" in page
        assert "estimado por contagem" in page
        assert 'data-sort="column"' in page
        assert "Controle, não ranking" not in page

    def test_html_with_judge_and_without_points(self) -> None:
        validation = JudgeValidation(
            "anthropic:x", "grounded_qa", 40, 0.71, "substancial", "2026-01-01"
        )
        page = render_html(
            _context(judge_validations=(validation,), points=(), frontier=(), sensitivity=())
        )
        assert "Validação de juiz automático" in page
        assert "0.710" in page
        assert "Nenhuma rodada encontrada" in page
        assert "Sensibilidade a prompt" not in page
        text = render_markdown(_context(judge_validations=(validation,), sensitivity=()))
        assert "substancial" in text and "## Sensibilidade" not in text

    def test_baseline_only_is_labeled_as_calibration(self) -> None:
        summary = _context().summaries[0]
        baseline_summary = replace(
            summary,
            key=replace(summary.key, provider="baseline", model="baseline-rules"),
        )
        context = _context(
            summaries=(baseline_summary,),
            publication=PublicationDecision(status="calibration", checks=()),
        )
        assert "Controle, não ranking" in render_html(context)
        assert "Estado: calibração do harness" in render_markdown(context)

    def test_frontier_label_anchor_flips_on_right_side(self) -> None:
        far = ParetoPoint("caro / p", 0.9, 0.05, 100)
        near = ParetoPoint("barato / p", 0.5, 0.0, 10)
        page = render_html(_context(points=(far, near), frontier=(far, near)))
        assert 'text-anchor="end"' in page and 'text-anchor="start"' in page


class TestBuild:
    def test_build_context_and_write_reports(
        self, tmp_path: Path, tasks: dict[str, TaskDefinition], pricing: PricingTable
    ) -> None:
        results = tmp_path / "results"
        observations = [
            make_observation(
                item_id="a", score=1.0, task="ticket_routing", details={"valid_label": True}
            )
        ]
        result = _run(observations, tasks=("ticket_routing",), model="cheap", prompt="minimal")
        write_run(result, results)
        (results / "judge_validation").mkdir()
        (results / "judge_validation" / "grounded_qa.json").write_text(
            json.dumps(
                JudgeValidation("j", "grounded_qa", 30, 0.65, "substancial", "2026-01-01").to_json()
            )
        )
        context = build_context(
            results_dir=results, tasks=tuple(tasks.values()), pricing=pricing, seed=1
        )
        assert context.dataset_sizes["ticket_routing"] == 150
        assert context.dataset_families["ticket_routing"] == 48
        assert context.judge_validations[0].accepted is True
        markdown_path, html_path, summary_path = write_reports(
            context, docs_dir=tmp_path / "docs", site_dir=tmp_path / "site"
        )
        assert markdown_path.exists() and html_path.exists()
        summary = json.loads(summary_path.read_text())
        assert summary["configurations"][0]["model"] == "cheap"
        assert summary["frontier"] == []
        assert summary["publication_status"] == "pre-publication"
        assert summary["publication_gates"]["passed"] is False
        assert summary["statistical_unit"] == "semantic_family"

    def test_build_context_requires_runs_and_consistent_datasets(
        self, tmp_path: Path, tasks: dict[str, TaskDefinition], pricing: PricingTable
    ) -> None:
        with pytest.raises(DomainError, match="nenhuma rodada"):
            build_context(
                results_dir=tmp_path, tasks=tuple(tasks.values()), pricing=pricing, seed=1
            )
        first = _run(
            [make_observation(item_id="a", score=1.0)],
            tasks=("ticket_routing",),
            model="cheap",
            prompt="minimal",
        )
        second = _run(
            [make_observation(item_id="a", score=1.0, prompt_name="optimized")],
            tasks=("ticket_routing",),
            model="cheap",
            prompt="optimized",
        )
        write_run(first, tmp_path)
        run_dir = write_run(second, tmp_path)
        manifest = json.loads((run_dir / "manifest.json").read_text())
        manifest["dataset_hashes"]["ticket_routing"] = "different"
        (run_dir / "manifest.json").write_text(json.dumps(manifest))
        with pytest.raises(DomainError, match="datasets diferentes"):
            build_context(
                results_dir=tmp_path, tasks=tuple(tasks.values()), pricing=pricing, seed=1
            )


class TestPublicationGates:
    def test_task_matrix_uses_observed_tasks_not_manifest_claims(self) -> None:
        observations = [
            replace(
                make_observation(
                    item_id="a",
                    score=1.0,
                    task="task_a",
                    model="real-model-2026-09-01",
                    repetition=repetition,
                ),
                provider="openai",
            )
            for repetition in range(3)
        ]
        now = utc_now()
        run = RunResult(
            RunSpec(
                ("task_a", "task_b"),
                "openai",
                "real-model-2026-09-01",
                "minimal",
                3,
                42,
                Split.PUBLIC,
            ),
            now,
            now,
            tuple(observations),
            {"task_a": "a", "task_b": "b"},
            "0.1.0",
        )
        decision = evaluate_publication(
            runs=(run,),
            summaries=summarize(observations, seed=1),
            required_tasks=frozenset({"task_a", "task_b"}),
            dataset_sizes={"task_a": 150, "task_b": 150},
            pricing=PricingTable(
                as_of=now.date().isoformat(),
                prices={"real-model-2026-09-01": ModelPrice(1.0, 2.0)},
            ),
        )
        task_matrix = next(check for check in decision.checks if check.key == "task_matrix")
        assert task_matrix.passed is False
        assert task_matrix.detail == "0/1 configurações completas"

    def test_cascade_rejects_placeholder_component_in_model_id(self) -> None:
        observation = replace(
            make_observation(item_id="a", score=1.0, model="expensive"),
            provider="cascade[baseline:baseline-rules->openai:expensive]",
        )
        now = utc_now()
        run = RunResult(
            RunSpec(
                ("ticket_routing",),
                observation.provider,
                "baseline-rules+expensive",
                "minimal",
                1,
                42,
                Split.PUBLIC,
            ),
            now,
            now,
            (observation,),
            {"ticket_routing": "h"},
            "0.1.0",
        )
        decision = evaluate_publication(
            runs=(run,),
            summaries=summarize([observation], seed=1),
            required_tasks=frozenset({"ticket_routing"}),
            dataset_sizes={"ticket_routing": 150},
            pricing=PricingTable(
                as_of=now.date().isoformat(),
                prices={"expensive": ModelPrice(1.0, 2.0)},
            ),
        )
        exact_ids = next(check for check in decision.checks if check.key == "exact_model_ids")
        assert exact_ids.passed is False


def test_interval_helper_used_in_context() -> None:
    interval = Interval(0.5, 0.4, 0.6, 10)
    assert interval.half_width == pytest.approx(0.1)
