"""Estatística usada nos relatórios.

Toda métrica publicada precisa vir acompanhada de intervalo de confiança.
Diferença sem intervalo não é diferença.
"""

from __future__ import annotations

import math
import random
from collections import Counter, defaultdict
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from statistics import mean, pstdev

from ptbr_benchmark.domain.models import DomainError, Observation


@dataclass(frozen=True, slots=True)
class Interval:
    point: float
    lower: float
    upper: float
    n: int

    def __post_init__(self) -> None:
        if not self.lower <= self.point <= self.upper:
            raise DomainError("intervalo inconsistente")
        if self.n < 0:
            raise DomainError("n negativo")

    @property
    def half_width(self) -> float:
        return (self.upper - self.lower) / 2

    def overlaps(self, other: Interval) -> bool:
        return self.lower <= other.upper and other.lower <= self.upper


def bootstrap_mean(
    values: Sequence[float],
    *,
    seed: int,
    resamples: int = 2000,
    confidence: float = 0.95,
) -> Interval:
    """Intervalo percentílico por bootstrap para a média."""
    if not values:
        raise DomainError("bootstrap exige pelo menos um valor")
    if not 0 < confidence < 1:
        raise DomainError("confiança deve estar em (0, 1)")
    if resamples < 100:
        raise DomainError("resamples abaixo de 100 não produz intervalo confiável")

    rng = random.Random(seed)
    n = len(values)
    point = mean(values)
    if n == 1:
        return Interval(point=point, lower=point, upper=point, n=1)

    means = sorted(mean(rng.choices(values, k=n)) for _ in range(resamples))
    alpha = (1 - confidence) / 2
    lower = means[math.floor(alpha * resamples)]
    upper = means[min(math.ceil((1 - alpha) * resamples) - 1, resamples - 1)]
    return Interval(
        point=point,
        lower=min(lower, point),
        upper=max(upper, point),
        n=n,
    )


def bootstrap_paired_difference(
    pairs: Sequence[tuple[float, float]],
    *,
    seed: int,
    resamples: int = 2000,
    confidence: float = 0.95,
) -> Interval:
    """IC percentílico do delta B-A em observações pareadas por item."""
    if not pairs:
        raise DomainError("bootstrap pareado exige pelo menos um par")
    differences = [right - left for left, right in pairs]
    return bootstrap_mean(
        differences,
        seed=seed,
        resamples=resamples,
        confidence=confidence,
    )


def cohens_kappa(rater_a: Sequence[str], rater_b: Sequence[str]) -> float:
    """Concordância entre dois avaliadores, corrigida pelo acaso.

    Usada para validar o juiz automático contra anotação humana. Sem essa
    validação, a pontuação do juiz não tem lastro.
    """
    if len(rater_a) != len(rater_b):
        raise DomainError("sequências de avaliação com tamanhos diferentes")
    if not rater_a:
        raise DomainError("kappa exige pelo menos uma avaliação")

    n = len(rater_a)
    observed = sum(1 for a, b in zip(rater_a, rater_b, strict=True) if a == b) / n
    dist_a = Counter(rater_a)
    dist_b = Counter(rater_b)
    expected = sum((dist_a[label] / n) * (dist_b[label] / n) for label in set(dist_a) | set(dist_b))
    if math.isclose(expected, 1.0):
        return 1.0
    return (observed - expected) / (1 - expected)


def interpret_kappa(kappa: float) -> str:
    if kappa < 0.2:
        return "insuficiente"
    if kappa < 0.4:
        return "fraca"
    if kappa < 0.6:
        return "moderada"
    if kappa < 0.8:
        return "substancial"
    return "quase perfeita"


@dataclass(frozen=True, slots=True)
class RepetitionSpread:
    """Quanto a mesma configuração varia entre repetições do mesmo item."""

    mean_within_item_std: float
    items_with_disagreement: int
    total_items: int

    @property
    def disagreement_rate(self) -> float:
        return self.items_with_disagreement / self.total_items if self.total_items else 0.0


def repetition_spread(observations: Iterable[Observation]) -> RepetitionSpread:
    by_item: dict[str, list[float]] = defaultdict(list)
    for observation in observations:
        by_item[observation.item_id].append(observation.score.value)
    if not by_item:
        raise DomainError("sem observações para medir variância")

    stds = [pstdev(scores) if len(scores) > 1 else 0.0 for scores in by_item.values()]
    disagreement = sum(1 for scores in by_item.values() if len(set(scores)) > 1)
    return RepetitionSpread(
        mean_within_item_std=mean(stds),
        items_with_disagreement=disagreement,
        total_items=len(by_item),
    )


def percentile(values: Sequence[float], q: float) -> float:
    """Percentil por interpolação linear. q em [0, 100]."""
    if not values:
        raise DomainError("percentil exige valores")
    if not 0 <= q <= 100:
        raise DomainError("q deve estar em [0, 100]")
    ordered = sorted(values)
    if len(ordered) == 1:
        return ordered[0]
    position = (len(ordered) - 1) * q / 100
    lower_index = math.floor(position)
    upper_index = math.ceil(position)
    if lower_index == upper_index:
        return ordered[lower_index]
    weight = position - lower_index
    return ordered[lower_index] * (1 - weight) + ordered[upper_index] * weight


@dataclass(frozen=True, slots=True)
class ParetoPoint:
    label: str
    quality: float
    cost_per_item_usd: float
    latency_p95_ms: float

    def dominates(self, other: ParetoPoint) -> bool:
        """Melhor ou igual em tudo, estritamente melhor em pelo menos um eixo."""
        at_least_as_good = (
            self.quality >= other.quality
            and self.cost_per_item_usd <= other.cost_per_item_usd
            and self.latency_p95_ms <= other.latency_p95_ms
        )
        strictly_better = (
            self.quality > other.quality
            or self.cost_per_item_usd < other.cost_per_item_usd
            or self.latency_p95_ms < other.latency_p95_ms
        )
        return at_least_as_good and strictly_better


def pareto_frontier(points: Sequence[ParetoPoint]) -> tuple[ParetoPoint, ...]:
    """Pontos não dominados. Ordem estável por custo crescente."""
    frontier = [
        candidate
        for candidate in points
        if not any(other.dominates(candidate) for other in points if other is not candidate)
    ]
    return tuple(sorted(frontier, key=lambda point: (point.cost_per_item_usd, -point.quality)))
