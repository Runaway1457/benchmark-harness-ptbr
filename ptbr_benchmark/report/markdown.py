"""Relatório em Markdown.

Determinístico: a mesma entrada produz o mesmo texto, byte a byte. Nenhum
timestamp de geração; as datas vêm dos manifestos das rodadas.
"""

from __future__ import annotations

from collections.abc import Sequence

from ptbr_benchmark.domain.metrics import ParetoPoint
from ptbr_benchmark.report.aggregate import ConfigSummary
from ptbr_benchmark.report.context import ReportContext, TaskInfo

_INTRO = (
    "Toda métrica principal vem com intervalo de confiança de 95% por bootstrap sobre "
    "famílias semânticas. Diferenças de prompt usam bootstrap pareado do delta nas mesmas "
    "famílias. "
    "Custo marcado com `~` é estimado a partir de contagem de caracteres, porque o provedor "
    "não devolveu uso de tokens."
)
_NO_JUDGE = (
    "Nenhum juiz automático foi validado contra anotação humana nesta publicação. "
    "Todas as pontuações acima vêm de pontuadores determinísticos."
)
_HASH_NOTE = (
    "O hash muda quando qualquer item muda. Comparar resultados entre publicações exige o "
    "mesmo hash."
)


def _pct(value: float) -> str:
    return f"{value * 100:.1f}%"


def _ci(summary: ConfigSummary) -> str:
    q = summary.quality
    return f"{_pct(q.point)} [{_pct(q.lower)}, {_pct(q.upper)}]"


def _cost(summary: ConfigSummary) -> str:
    marker = "~" if summary.cost_estimated else ""
    return f"{marker}${summary.cost_per_item_usd:.5f}"


def _row(*cells: object) -> str:
    return "| " + " | ".join(str(cell) for cell in cells) + " |"


def render_markdown(context: ReportContext) -> str:
    sections = [
        _intro(context),
        _pareto(context.points, context.frontier),
        *(_task(task, context) for task in context.tasks),
        _sensitivity(context),
        _judge(context),
        _datasets(context),
    ]
    return "\n".join(section for section in sections if section)


def _intro(context: ReportContext) -> str:
    lines = [
        "# Resultados",
        "",
        f"Harness `ptbr-benchmark {context.harness_version}`. Preços de referência em "
        f"{context.pricing_as_of}. Rodadas concluídas até {context.latest_run_at}.",
        "",
        _INTRO,
        "",
    ]
    if context.publication.status == "calibration":
        lines.extend(
            [
                "> **Estado: calibração do harness.** Este snapshot contém somente o baseline "
                "determinístico. Ele valida o pipeline e não sustenta comparação entre "
                "fornecedores.",
                "",
                "### Portões de calibração",
                "",
                _row("Gate", "Estado", "Evidência"),
                "|---|:---:|---|",
                *(
                    _row(
                        check.label,
                        "passou" if check.passed else "bloqueado",
                        check.detail,
                    )
                    for check in context.publication.checks
                ),
                "",
            ]
        )
    elif context.publication.status == "pre-publication":
        lines.extend(
            [
                "> **Estado: pré-publicação.** Há resultados de modelos reais, mas pelo "
                "menos um portão executável ainda bloqueia a publicação.",
                "",
                "### Portões de publicação",
                "",
                _row("Gate", "Estado", "Evidência"),
                "|---|:---:|---|",
                *(
                    _row(
                        check.label,
                        "passou" if check.passed else "bloqueado",
                        check.detail,
                    )
                    for check in context.publication.checks
                ),
                "",
            ]
        )
    return "\n".join(lines)


def _pareto(points: Sequence[ParetoPoint], frontier: Sequence[ParetoPoint]) -> str:
    frontier_labels = {point.label for point in frontier}
    lines = [
        "## Fronteira de Pareto",
        "",
        "Qualidade média entre tarefas, custo médio por item e p95 de latência.",
        "",
        _row("Configuração", "Qualidade", "Custo por item", "p95 (ms)", "Fronteira"),
        "|---|---:|---:|---:|:---:|",
    ]
    for point in sorted(points, key=lambda p: (p.cost_per_item_usd, -p.quality)):
        lines.append(
            _row(
                point.label,
                _pct(point.quality),
                f"${point.cost_per_item_usd:.5f}",
                f"{point.latency_p95_ms:.0f}",
                "sim" if point.label in frontier_labels else "",
            )
        )
    lines.append("")
    return "\n".join(lines)


def _task(task: TaskInfo, context: ReportContext) -> str:
    summaries = [s for s in context.summaries if s.key.task == task.name]
    if not summaries:
        return ""
    lines = [
        f"## {task.name}",
        "",
        task.description + ".",
        "",
        _row(
            "Modelo / prompt",
            "Qualidade [IC 95%]",
            "Custo por item",
            "p50 (ms)",
            "p95 (ms)",
            "Divergência entre repetições",
            "Itens",
            "Erros",
        ),
        "|---|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for s in summaries:
        lines.append(
            _row(
                s.key.label,
                _ci(s),
                _cost(s),
                f"{s.latency_p50_ms:.0f}",
                f"{s.latency_p95_ms:.0f}",
                _pct(s.spread.disagreement_rate),
                s.items,
                _pct(s.error_rate),
            )
        )
    lines.append("")
    extras = _extras(task.name, summaries)
    if extras:
        lines.extend(extras)
        lines.append("")
    return "\n".join(lines)


def _rate_rows(
    summaries: Sequence[ConfigSummary], *, headers: Sequence[str], keys: Sequence[str]
) -> list[str]:
    lines = [_row("Modelo / prompt", *headers), "|---|" + "---:|" * len(headers)]
    lines.extend(
        _row(s.key.label, *(_pct(s.extra.get(key, 0.0)) for key in keys)) for s in summaries
    )
    return lines


def _extras(task: str, summaries: Sequence[ConfigSummary]) -> list[str]:
    if task == "lgpd_refusal":
        return _rate_rows(
            summaries,
            headers=("Vazamento (respondeu quando devia recusar)", "Recusa indevida"),
            keys=("leak_rate", "over_refusal_rate"),
        )
    if task == "grounded_qa":
        return _rate_rows(
            summaries,
            headers=("Citação inventada", "Resposta inventada", "Erro de contrato"),
            keys=(
                "invented_citation_rate",
                "hallucinated_answer_rate",
                "response_contract_error_rate",
            ),
        )
    if task == "fiscal_extraction":
        return _fiscal_extras(summaries)
    if task == "ticket_routing":
        return _rate_rows(
            summaries,
            headers=("F1 macro", "Acurácia", "Rótulo inválido"),
            keys=("macro_f1", "accuracy", "invalid_label_rate"),
        )
    if task == "regional_ptbr":
        return _rate_rows(
            summaries,
            headers=("Resposta fora do formato",),
            keys=("invalid_answer_rate",),
        )
    return []


def _fiscal_extras(summaries: Sequence[ConfigSummary]) -> list[str]:
    fields = sorted({name for s in summaries for name in s.extra.get("field_accuracy", {})})
    if not fields:
        return []
    lines = [
        "Acurácia por campo:",
        "",
        _row("Campo", *(s.key.label for s in summaries)),
        "|---|" + "---:|" * len(summaries),
    ]
    for field_name in fields:
        lines.append(
            _row(
                field_name,
                *(_pct(s.extra.get("field_accuracy", {}).get(field_name, 0.0)) for s in summaries),
            )
        )
    lines.append("")
    lines.extend(
        _rate_rows(
            summaries,
            headers=("Documento 100% correto", "Erro de parse"),
            keys=("all_fields_correct_rate", "parse_error_rate"),
        )
    )
    return lines


def _sensitivity(context: ReportContext) -> str:
    if not context.sensitivity:
        return ""
    lines = [
        "## Sensibilidade a prompt",
        "",
        "Mesma tarefa, mesmo modelo, prompts diferentes. O IC 95% é calculado sobre o delta "
        "pareado por família semântica; `significativo` quando esse intervalo exclui zero.",
        "",
        _row(
            "Tarefa",
            "Modelo",
            "Prompt A",
            "Prompt B",
            "Qualidade A",
            "Qualidade B",
            "Delta",
            "IC 95% do delta",
            "Significativo",
        ),
        "|---|---|---|---|---:|---:|---:|---:|:---:|",
    ]
    for c in context.sensitivity:
        lines.append(
            _row(
                c.task,
                c.model,
                c.prompt_a,
                c.prompt_b,
                _pct(c.quality_a.point),
                _pct(c.quality_b.point),
                f"{c.delta * 100:+.1f} pp",
                (
                    f"[{c.paired_delta.lower * 100:+.1f}, {c.paired_delta.upper * 100:+.1f}] pp"
                    if c.paired_delta is not None
                    else "n/d"
                ),
                "sim" if c.significant else "não",
            )
        )
    lines.append("")
    return "\n".join(lines)


def _judge(context: ReportContext) -> str:
    lines = ["## Validação de juiz", ""]
    if context.judge_validations:
        lines.append(_row("Tarefa", "Juiz", "Amostra", "Kappa", "Interpretação", "Aceito"))
        lines.append("|---|---|---:|---:|---|:---:|")
        lines.extend(
            _row(
                v.task,
                v.judge,
                v.sample_size,
                f"{v.kappa:.3f}",
                v.interpretation,
                "sim" if v.accepted else "não",
            )
            for v in context.judge_validations
        )
    else:
        lines.append(_NO_JUDGE)
    lines.append("")
    return "\n".join(lines)


def _datasets(context: ReportContext) -> str:
    lines = [
        "## Datasets",
        "",
        _row("Tarefa", "Itens públicos", "Famílias semânticas", "Hash do dataset"),
        "|---|---:|---:|---|",
    ]
    for task in context.tasks:
        digest = context.dataset_hashes.get(task.name, "n/d")[:16]
        lines.append(
            _row(
                task.name,
                context.dataset_sizes.get(task.name, 0),
                context.dataset_families.get(task.name, 0),
                f"`{digest}`",
            )
        )
    lines.extend(["", _HASH_NOTE, ""])
    return "\n".join(lines)
