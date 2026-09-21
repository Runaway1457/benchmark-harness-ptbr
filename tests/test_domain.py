from __future__ import annotations

from datetime import timedelta

import pytest

from ptbr_benchmark.domain.metrics import (
    Interval,
    ParetoPoint,
    bootstrap_mean,
    bootstrap_paired_difference,
    cohens_kappa,
    interpret_kappa,
    pareto_frontier,
    percentile,
    repetition_spread,
)
from ptbr_benchmark.domain.models import (
    Completion,
    DomainError,
    Item,
    Prompt,
    RunResult,
    RunSpec,
    Score,
    ScoringKind,
    Split,
    Usage,
    stable_hash,
    utc_now,
)
from tests.conftest import make_observation


class TestModels:
    def test_item_rejects_empty_fields(self) -> None:
        with pytest.raises(DomainError):
            Item(id=" ", task="t", input={"a": 1}, expected={"b": 2})
        with pytest.raises(DomainError):
            Item(id="x", task="t", input={}, expected={"b": 2})
        with pytest.raises(DomainError):
            Item(id="x", task="t", input={"a": 1}, expected={})
        with pytest.raises(DomainError):
            Item(id="x", task="", input={"a": 1}, expected={"b": 2})

    def test_item_content_hash_ignores_id(self) -> None:
        a = Item(id="1", task="t", input={"a": 1}, expected={"b": 2})
        b = Item(id="2", task="t", input={"a": 1}, expected={"b": 2})
        assert a.content_hash == b.content_hash

    def test_prompt_version_changes_with_content(self) -> None:
        a = Prompt(name="p", template="Olá {x}")
        b = Prompt(name="p", template="Olá {x}!")
        assert a.version != b.version
        assert a.render(x="mundo") == "Olá mundo"

    def test_prompt_missing_variable(self) -> None:
        with pytest.raises(DomainError, match="exige variável"):
            Prompt(name="p", template="{missing}").render(other=1)
        with pytest.raises(DomainError):
            Prompt(name="p", template="   ")

    def test_usage_and_completion_invariants(self) -> None:
        with pytest.raises(DomainError):
            Usage(input_tokens=-1, output_tokens=0)
        usage = Usage(input_tokens=3, output_tokens=4)
        assert usage.total_tokens == 7
        with pytest.raises(DomainError):
            Completion(text="", model="m", usage=usage, latency_ms=-1)
        with pytest.raises(DomainError):
            Completion(text="", model="m", usage=usage, latency_ms=1, attempts=0)
        with pytest.raises(DomainError):
            Completion(text="", model="m", usage=usage, latency_ms=1, cost_usd=-0.1)

    def test_score_bounds(self) -> None:
        with pytest.raises(DomainError):
            Score(value=1.2, kind=ScoringKind.EXACT)
        with pytest.raises(DomainError):
            Score(value=-0.1, kind=ScoringKind.EXACT)

    def test_observation_invariants(self) -> None:
        with pytest.raises(DomainError):
            make_observation(item_id="a", score=1.0, repetition=-1)
        with pytest.raises(DomainError):
            make_observation(item_id="a", score=1.0, cost=-0.1)

    def test_run_spec_id_is_stable_and_order_independent(self) -> None:
        a = RunSpec(("x", "y"), "p", "m", "minimal", 3, 42, Split.PUBLIC)
        b = RunSpec(("y", "x"), "p", "m", "minimal", 3, 42, Split.PUBLIC)
        c = RunSpec(("x", "y"), "p", "m", "minimal", 3, 43, Split.PUBLIC)
        assert a.run_id == b.run_id
        assert a.run_id != c.run_id
        assert len(a.run_id) == 16

    def test_run_spec_invariants(self) -> None:
        with pytest.raises(DomainError):
            RunSpec((), "p", "m", "minimal", 3, 42, Split.PUBLIC)
        with pytest.raises(DomainError):
            RunSpec(("x",), "p", "m", "minimal", 0, 42, Split.PUBLIC)
        with pytest.raises(DomainError):
            RunSpec(("x",), "p", "m", "minimal", 1, 42, Split.PUBLIC, limit=0)

    def test_run_result_time_ordering_and_cost(self) -> None:
        spec = RunSpec(("x",), "p", "m", "minimal", 1, 42, Split.PUBLIC)
        now = utc_now()
        obs = (make_observation(item_id="a", score=1.0, cost=0.5),)
        with pytest.raises(DomainError):
            RunResult(spec, now, now - timedelta(seconds=1), obs, {}, "0.1.0")
        result = RunResult(spec, now, now, obs, {}, "0.1.0")
        assert result.total_cost_usd == 0.5

    def test_stable_hash_is_canonical(self) -> None:
        assert stable_hash({"b": 1, "a": 2}) == stable_hash({"a": 2, "b": 1})


class TestBootstrap:
    def test_interval_contains_point_and_shrinks_with_n(self) -> None:
        small = bootstrap_mean([0.0, 1.0, 1.0, 0.0], seed=1)
        large = bootstrap_mean([0.0, 1.0] * 200, seed=1)
        assert small.lower <= small.point <= small.upper
        assert large.half_width < small.half_width
        assert large.n == 400

    def test_single_value_is_degenerate(self) -> None:
        interval = bootstrap_mean([0.7], seed=1)
        assert interval.lower == interval.upper == interval.point == 0.7

    def test_constant_values_have_zero_width(self) -> None:
        interval = bootstrap_mean([1.0] * 50, seed=1)
        assert interval.half_width == 0.0

    def test_deterministic_by_seed(self) -> None:
        values = [0.2, 0.9, 0.5, 0.1, 0.8, 0.3]
        assert bootstrap_mean(values, seed=7) == bootstrap_mean(values, seed=7)
        assert bootstrap_mean(values, seed=7) != bootstrap_mean(values, seed=8)

    def test_rejects_bad_arguments(self) -> None:
        with pytest.raises(DomainError):
            bootstrap_mean([], seed=1)
        with pytest.raises(DomainError):
            bootstrap_mean([1.0, 0.0], seed=1, confidence=1.5)
        with pytest.raises(DomainError):
            bootstrap_mean([1.0, 0.0], seed=1, resamples=10)

    def test_interval_invariants_and_overlap(self) -> None:
        with pytest.raises(DomainError):
            Interval(point=0.5, lower=0.6, upper=0.7, n=3)
        with pytest.raises(DomainError):
            Interval(point=0.5, lower=0.4, upper=0.6, n=-1)
        a = Interval(0.5, 0.4, 0.6, 10)
        b = Interval(0.55, 0.5, 0.7, 10)
        c = Interval(0.9, 0.8, 1.0, 10)
        assert a.overlaps(b) and b.overlaps(a)
        assert not a.overlaps(c)

    def test_paired_difference_uses_within_pair_delta(self) -> None:
        interval = bootstrap_paired_difference([(0.1, 0.4), (0.2, 0.5), (0.3, 0.6)], seed=9)
        assert interval.point == pytest.approx(0.3)
        assert interval.lower == pytest.approx(0.3)
        assert interval.upper == pytest.approx(0.3)
        assert interval.n == 3
        with pytest.raises(DomainError, match="pelo menos um par"):
            bootstrap_paired_difference([], seed=9)


class TestKappa:
    def test_perfect_agreement(self) -> None:
        assert cohens_kappa(["a", "b", "a"], ["a", "b", "a"]) == 1.0

    def test_known_value(self) -> None:
        rater_a = ["y", "y", "y", "y", "y", "y", "y", "y", "y", "y", "n", "n", "n", "n", "n"]
        rater_b = ["y", "y", "y", "y", "y", "y", "y", "y", "n", "n", "n", "n", "n", "n", "y"]
        kappa = cohens_kappa(rater_a, rater_b)
        assert 0.57 < kappa < 0.60

    def test_chance_level_is_zero(self) -> None:
        rater_a = ["a", "a", "b", "b"]
        rater_b = ["a", "b", "a", "b"]
        assert abs(cohens_kappa(rater_a, rater_b)) < 1e-9

    def test_all_same_label_both_raters(self) -> None:
        assert cohens_kappa(["a", "a"], ["a", "a"]) == 1.0

    def test_rejects_bad_input(self) -> None:
        with pytest.raises(DomainError):
            cohens_kappa(["a"], ["a", "b"])
        with pytest.raises(DomainError):
            cohens_kappa([], [])

    def test_interpretation_bands(self) -> None:
        assert interpret_kappa(0.1) == "insuficiente"
        assert interpret_kappa(0.3) == "fraca"
        assert interpret_kappa(0.5) == "moderada"
        assert interpret_kappa(0.7) == "substancial"
        assert interpret_kappa(0.9) == "quase perfeita"


class TestSpreadAndPercentile:
    def test_repetition_spread_detects_disagreement(self) -> None:
        observations = [
            make_observation(item_id="a", score=1.0, repetition=0),
            make_observation(item_id="a", score=0.0, repetition=1),
            make_observation(item_id="b", score=1.0, repetition=0),
            make_observation(item_id="b", score=1.0, repetition=1),
        ]
        spread = repetition_spread(observations)
        assert spread.items_with_disagreement == 1
        assert spread.total_items == 2
        assert spread.disagreement_rate == 0.5
        assert spread.mean_within_item_std == 0.25

    def test_repetition_spread_requires_observations(self) -> None:
        with pytest.raises(DomainError):
            repetition_spread([])

    def test_percentile_interpolates(self) -> None:
        values = [10.0, 20.0, 30.0, 40.0]
        assert percentile(values, 0) == 10.0
        assert percentile(values, 100) == 40.0
        assert percentile(values, 50) == 25.0
        assert percentile([5.0], 95) == 5.0
        with pytest.raises(DomainError):
            percentile([], 50)
        with pytest.raises(DomainError):
            percentile([1.0], 101)


class TestPareto:
    def test_dominance(self) -> None:
        cheap_good = ParetoPoint("a", 0.9, 0.001, 100)
        expensive_worse = ParetoPoint("b", 0.8, 0.002, 200)
        expensive_better = ParetoPoint("c", 0.95, 0.002, 200)
        assert cheap_good.dominates(expensive_worse)
        assert not cheap_good.dominates(expensive_better)
        assert not expensive_better.dominates(cheap_good)

    def test_identical_points_do_not_dominate_each_other(self) -> None:
        a = ParetoPoint("a", 0.9, 0.001, 100)
        b = ParetoPoint("b", 0.9, 0.001, 100)
        assert not a.dominates(b)
        assert set(p.label for p in pareto_frontier([a, b])) == {"a", "b"}

    def test_frontier_ordering_and_membership(self) -> None:
        points = [
            ParetoPoint("free", 0.6, 0.0, 5),
            ParetoPoint("mid", 0.8, 0.001, 300),
            ParetoPoint("dominated", 0.7, 0.002, 400),
            ParetoPoint("best", 0.95, 0.01, 800),
        ]
        frontier = pareto_frontier(points)
        assert [p.label for p in frontier] == ["free", "mid", "best"]
