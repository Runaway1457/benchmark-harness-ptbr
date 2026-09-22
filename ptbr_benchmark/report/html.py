"""Site estático de resultados.

Um único arquivo HTML, sem requisição externa, sem build. O CSS vem de
report.css e é embutido; o gráfico de Pareto é SVG gerado aqui.
Determinístico: a mesma entrada produz o mesmo arquivo, byte a byte, e um
teste verifica isso por hash.
"""

from __future__ import annotations

import html
from collections.abc import Callable, Sequence
from pathlib import Path

from ptbr_benchmark.domain.metrics import ParetoPoint
from ptbr_benchmark.report.aggregate import ConfigSummary
from ptbr_benchmark.report.context import ReportContext

_CSS_PATH = Path(__file__).with_name("report.css")

_HEADLINE = "Qual modelo entrega mais em português brasileiro?"
_LEDE = (
    "Cinco tarefas corporativas, dado sintético com textura brasileira, métrica com "
    "intervalo de confiança. Custo e latência medidos junto com a qualidade, porque o "
    "modelo mais preciso raramente é a escolha certa."
)
_PARETO_NOTE = (
    "Cada ponto é uma combinação de modelo e prompt, com a qualidade média entre as tarefas "
    "e o custo médio por item. A linha liga as configurações que ninguém supera em qualidade "
    "sem gastar mais."
)
_ESTIMATED_COST = (
    "Custo de configurações marcadas com ~ é estimado por contagem de caracteres, porque o "
    "provedor não devolveu uso de tokens. Não compare custo estimado com custo medido."
)
_SENSITIVITY_NOTE = (
    "Mesma tarefa, mesmo modelo, prompt diferente. O intervalo é do delta pareado por item; "
    "ele precisa excluir zero antes de tratarmos a diferença como evidência."
)
_READING_1 = (
    "Cada item é avaliado em repetições independentes. A qualidade publicada é a média por "
    "item, com intervalo de confiança de 95% por bootstrap. Comparações de prompt usam os "
    "mesmos itens em um bootstrap pareado."
)
_READING_2 = (
    "A coluna de divergência mostra em quantos itens o mesmo modelo, com o mesmo prompt, deu "
    "respostas com pontuação diferente entre repetições. Modelo não determinístico é a regra, "
    "não a exceção."
)
_NO_JUDGE = (
    "Nenhuma pontuação nesta publicação vem de juiz automático. Todas as tarefas usam "
    "pontuador determinístico. Quando um juiz for adicionado, ele só entra no relatório após "
    "validação contra anotação humana com kappa mínimo de 0,6."
)
_FOOTER = "Benchmark reproduzível para decisões de modelo em português brasileiro."
_LGPD_NOTE = (
    "Vazamento é responder quando devia recusar: incidente. Recusa indevida é recusar pedido "
    "legítimo: atrito. Um modelo que só recusa zera o vazamento e inutiliza o assistente."
)
_GQA_NOTE = (
    "Citação inventada é apontar para um trecho que não existe. Resposta inventada é "
    "responder uma pergunta cuja resposta não está no documento. Erro de contrato é uma "
    "recusa semanticamente correta fora do formato exigido; continua falhando, mas não é "
    "rotulada como alucinação."
)
_FISCAL_NOTE = (
    "A média por documento esconde onde o modelo erra. CNPJ e valor total pesam mais na "
    "qualidade agregada porque errar neles custa mais."
)
_FIGCAPTION = (
    "Passe o cursor sobre um ponto para ver o detalhe. As configurações na fronteira são as "
    "únicas que vale considerar; as demais custam mais para a mesma qualidade, ou entregam "
    "menos pelo mesmo custo."
)

_SORT_SCRIPT = r"""
<script>
(() => {
  const number = value => {
    const cleaned = value.replace(/[^0-9,.-+]/g, "").replace(",", ".");
    const parsed = Number.parseFloat(cleaned);
    return Number.isFinite(parsed) ? parsed : null;
  };
  document.querySelectorAll("th button[data-sort]").forEach(button => {
    button.addEventListener("click", () => {
      const table = button.closest("table");
      const body = table.querySelector("tbody");
      const index = [...button.parentElement.parentElement.children].indexOf(button.parentElement);
      const direction = button.dataset.direction === "asc" ? "desc" : "asc";
      table.querySelectorAll("th button").forEach(item => item.removeAttribute("data-direction"));
      button.dataset.direction = direction;
      const rows = [...body.querySelectorAll("tr")];
      rows.sort((a, b) => {
        const left = a.children[index].textContent.trim();
        const right = b.children[index].textContent.trim();
        const leftNumber = number(left);
        const rightNumber = number(right);
        const result = leftNumber !== null && rightNumber !== null
          ? leftNumber - rightNumber
          : left.localeCompare(right, "pt-BR", {numeric: true});
        return direction === "asc" ? result : -result;
      });
      rows.forEach(row => body.appendChild(row));
    });
  });
  document.querySelectorAll("[data-table-search]").forEach(input => {
    input.addEventListener("input", () => {
      const query = input.value.toLocaleLowerCase("pt-BR");
      input.closest("section").querySelectorAll("tbody tr").forEach(row => {
        row.hidden = !row.textContent.toLocaleLowerCase("pt-BR").includes(query);
      });
    });
  });
})();
</script>"""


def _pct(value: float) -> str:
    return f"{value * 100:.1f}%"


def _esc(value: object) -> str:
    return html.escape(str(value), quote=True)


def _th(label: str, *, numeric: bool = False) -> str:
    css = ' class="num"' if numeric else ""
    return f'<th{css}><button type="button" data-sort="column">{_esc(label)}</button></th>'


def _td(value: str, *, numeric: bool = False, raw: bool = False) -> str:
    content = value if raw else _esc(value)
    return f'<td class="num">{content}</td>' if numeric else f"<td>{content}</td>"


def _table(header: Sequence[str], rows: Sequence[str]) -> str:
    return (
        '<div class="scroll"><table class="data-table"><thead><tr>'
        + "".join(header)
        + "</tr></thead><tbody>"
        + "".join(rows)
        + "</tbody></table></div>"
    )


def render_html(context: ReportContext) -> str:
    parts: list[str] = [
        "<!doctype html>",
        '<html lang="pt-BR">',
        "<head>",
        '<meta charset="utf-8">',
        '<meta name="viewport" content="width=device-width, initial-scale=1">',
        '<meta name="theme-color" content="#06070b">',
        '<meta http-equiv="Content-Security-Policy" '
        'content="default-src &#39;none&#39;; style-src &#39;unsafe-inline&#39;; '
        "script-src &#39;unsafe-inline&#39;; img-src data:; base-uri &#39;none&#39;; "
        'form-action &#39;none&#39;">',
        '<meta name="description" '
        'content="Benchmark reproduzível para tarefas corporativas em português brasileiro.">',
        "<title>Benchmark e Harness de Avaliação PT-BR · "
        "Model intelligence for Brazilian Portuguese</title>",
        f"<style>\n{_CSS_PATH.read_text(encoding='utf-8')}</style>",
        "</head>",
        "<body>",
        _topbar(),
        "<main>",
        _header(context),
        _metrics(context),
        _pareto_section(context),
    ]
    for task in context.tasks:
        summaries = [s for s in context.summaries if s.key.task == task.name]
        if summaries:
            parts.append(_task_section(task.name, task.description, summaries))
    if context.sensitivity:
        parts.append(_sensitivity_section(context))
    parts.append(_reading_section(context))
    parts.append(
        "<footer><span><strong>Benchmark e Harness de Avaliação PT-BR</strong> · "
        f"{_esc(_FOOTER)}</span>"
        f"<span>v{_esc(context.harness_version)} · {_esc(context.latest_run_at)}</span></footer>"
    )
    parts.append(_SORT_SCRIPT)
    parts.append("</main></body></html>")
    return "\n".join(parts) + "\n"


def _topbar() -> str:
    return (
        '<nav class="topbar" aria-label="Navegação principal"><div class="topbar-inner">'
        '<div class="brand"><span class="brand-mark">E</span><span>Eval<em>BR</em></span></div>'
        '<div class="nav"><a href="#overview">Overview</a><a href="#frontier">Pareto</a>'
        '<a href="#task-fiscal_extraction">Tarefas</a><a href="#methodology">Metodologia</a></div>'
        "</div></nav>"
    )


def _header(context: ReportContext) -> str:
    state = {
        "calibration": "Calibração do harness · matriz de modelos pendente",
        "simulation": "Demonstração sintética · não representa modelos reais",
        "pre-publication": "Pré-publicação · gates ainda não atendidos",
        "published": "Benchmark publicado · gates aprovados",
    }[context.publication.status]
    bars = (28, 44, 34, 68, 51, 79, 58, 92, 70, 48, 63, 84, 55, 73, 96, 67, 81, 60)
    signal = "".join(
        f'<i style="--h:{height}%;--o:{0.42 + (index % 4) * 0.16:.2f}"></i>'
        for index, height in enumerate(bars)
    )
    return (
        '<header class="hero" id="overview"><div>'
        '<p class="eyebrow">Brazilian Portuguese Model Intelligence</p>'
        f"<h1>Qual modelo entrega mais em <span>português brasileiro?</span></h1>"
        f'<p class="lede">{_esc(_LEDE)}</p>'
        f'<div class="status-line"><span class="status-dot"></span>{_esc(state)}</div>'
        '</div><aside class="hero-console" aria-label="Sinal de avaliação">'
        '<div class="console-head"><span>benchmark / signal</span><span class="console-dots">'
        "<i></i><i></i><i></i></span></div>"
        f'<div class="signal" aria-hidden="true">{signal}</div>'
        '<div class="console-row"><span>harness</span>'
        f"<strong>v{_esc(context.harness_version)}</strong></div>"
        '<div class="console-row"><span>pricing snapshot</span>'
        f"<strong>{_esc(context.pricing_as_of)}</strong></div>"
        '<div class="console-row"><span>latest run</span>'
        f"<strong>{_esc(context.latest_run_at)}</strong></div>"
        "</aside>"
        "</header>"
    )


def _metrics(context: ReportContext) -> str:
    items = sum(context.dataset_sizes.values())
    families = sum(context.dataset_families.values())
    configurations = len(
        {(s.key.provider, s.key.model, s.key.prompt_name) for s in context.summaries}
    )
    return (
        '<div class="metrics" aria-label="Resumo do benchmark">'
        f'<div class="metric"><b>{items}</b><span>itens públicos</span>'
        "<small>5 tarefas corporativas</small></div>"
        f'<div class="metric"><b>{families}</b><span>famílias semânticas</span>'
        "<small>unidade estatística</small></div>"
        f'<div class="metric"><b>{configurations}</b><span>configurações executadas</span>'
        "<small>modelo / prompt</small></div>"
        '<div class="metric"><b>95%</b><span>intervalo de confiança</span>'
        "<small>bootstrap por família</small></div>"
        "</div>"
    )


def _pareto_section(context: ReportContext) -> str:
    calibration = context.publication.status == "calibration"
    parts = [
        '<section id="frontier">',
        '<div class="section-head"><div><p class="section-kicker">Decision surface</p>'
        "<h2>Qualidade &times; custo</h2></div>",
        f'<p class="note">{_esc(_PARETO_NOTE)}</p></div>',
    ]
    if calibration:
        parts.append(
            '<p class="calibration-banner"><strong>Controle, não ranking.</strong> '
            "A publicação atual contém somente o baseline determinístico para validar o pipeline. "
            "Nenhuma conclusão sobre fornecedores é apresentada sem rodadas reais.</p>"
        )
    elif context.publication.status == "simulation":
        parts.append(
            '<p class="calibration-banner"><strong>Simulação, não ranking.</strong> '
            "Cada perfil sintético leva “(simulado)” no próprio rótulo. Nenhum fornecedor "
            "real foi medido neste artefato.</p>"
        )
    elif context.publication.status == "pre-publication":
        parts.append(
            '<p class="calibration-banner"><strong>Pré-publicação.</strong> '
            "Há chamadas de modelos reais, mas a matriz não pode ser tratada como publicada "
            "até todos os portões executáveis passarem.</p>"
        )
    if context.pareto_exclusions:
        excluded = "; ".join(
            f"{label}: {', '.join(reasons)}" for label, reasons in context.pareto_exclusions.items()
        )
        parts.append(
            '<p class="caution"><strong>Fora da superfície de decisão:</strong> '
            f"{_esc(excluded)}.</p>"
        )
    parts.extend(
        [
            '<div class="chart-shell">',
            _pareto_svg(context.points, context.frontier),
            '<div class="legend"><span class="f">Na fronteira</span>'
            '<span class="o">Dominada por outra configuração</span></div>',
            "</div>",
            '<div class="toolbar"><input type="search" data-table-search '
            'aria-label="Filtrar configurações" placeholder="Filtrar configuração…">'
            f'<span class="count">{len(context.points)} configurações</span></div>',
            _pareto_table(context.points, context.frontier),
        ]
    )
    if any(s.cost_estimated for s in context.summaries):
        parts.append(f'<p class="caution">{_esc(_ESTIMATED_COST)}</p>')
    parts.append("</section>")
    return "".join(parts)


def _pareto_table(points: Sequence[ParetoPoint], frontier: Sequence[ParetoPoint]) -> str:
    frontier_labels = {p.label for p in frontier}
    header = [
        _th("Configuração"),
        _th("Qualidade", numeric=True),
        _th("Custo por item", numeric=True),
        _th("p95", numeric=True),
    ]
    rows: list[str] = []
    for point in sorted(points, key=lambda p: (p.cost_per_item_usd, -p.quality)):
        cls = ' class="frontier"' if point.label in frontier_labels else ""
        rows.append(
            f"<tr{cls}>"
            + _td(point.label)
            + _td(_pct(point.quality), numeric=True)
            + _td(f"${point.cost_per_item_usd:.5f}", numeric=True)
            + _td(f"{point.latency_p95_ms:.0f} ms", numeric=True)
            + "</tr>"
        )
    return _table(header, rows)


def _task_section(name: str, description: str, summaries: Sequence[ConfigSummary]) -> str:
    extras = _task_extras(name, summaries)
    if any("cascade_escalation_rate" in summary.extra for summary in summaries):
        extras.extend(
            [
                "<h3>Roteamento em cascata</h3>",
                _rate_table(
                    summaries,
                    columns=(("Itens escalados", "cascade_escalation_rate"),),
                ),
            ]
        )
    parts = [
        f'<section class="task-card" id="task-{_esc(name)}">',
        '<div class="section-head"><div>'
        f'<span class="task-id">{_esc(name.replace("_", " "))}</span>'
        f"<h2>{_esc(name)}</h2></div>"
        f'<p class="note">{_esc(description)}.</p></div>',
        _summary_table(summaries),
        *extras,
        "</section>",
    ]
    return "".join(parts)


def _summary_table(summaries: Sequence[ConfigSummary]) -> str:
    header = [
        _th("Modelo / prompt"),
        _th("Qualidade [IC 95%]", numeric=True),
        _th("Custo por item", numeric=True),
        _th("p50", numeric=True),
        _th("p95", numeric=True),
        _th("Divergência", numeric=True),
        _th("Itens", numeric=True),
        _th("Erros", numeric=True),
    ]
    rows: list[str] = []
    for s in summaries:
        marker = "~" if s.cost_estimated else ""
        quality = (
            f"{_pct(s.quality.point)} "
            f"<small>[{_pct(s.quality.lower)}, {_pct(s.quality.upper)}]</small>"
        )
        rows.append(
            "<tr>"
            + _td(s.key.label)
            + _td(quality, numeric=True, raw=True)
            + _td(f"{marker}${s.cost_per_item_usd:.5f}", numeric=True)
            + _td(f"{s.latency_p50_ms:.0f} ms", numeric=True)
            + _td(f"{s.latency_p95_ms:.0f} ms", numeric=True)
            + _td(_pct(s.spread.disagreement_rate), numeric=True)
            + _td(str(s.items), numeric=True)
            + _td(_pct(s.error_rate), numeric=True)
            + "</tr>"
        )
    return _table(header, rows)


def _rate_table(summaries: Sequence[ConfigSummary], *, columns: Sequence[tuple[str, str]]) -> str:
    header = [_th("Modelo / prompt"), *(_th(label, numeric=True) for label, _ in columns)]
    rows = [
        "<tr>"
        + _td(s.key.label)
        + "".join(_td(_pct(s.extra.get(key, 0.0)), numeric=True) for _, key in columns)
        + "</tr>"
        for s in summaries
    ]
    return _table(header, rows)


def _task_extras(task: str, summaries: Sequence[ConfigSummary]) -> list[str]:
    if task == "lgpd_refusal":
        return [
            "<h3>Os dois erros, separados</h3>",
            f'<p class="note">{_esc(_LGPD_NOTE)}</p>',
            _rate_table(
                summaries,
                columns=(("Vazamento", "leak_rate"), ("Recusa indevida", "over_refusal_rate")),
            ),
        ]
    if task == "grounded_qa":
        return [
            "<h3>Alucinação</h3>",
            f'<p class="note">{_esc(_GQA_NOTE)}</p>',
            _rate_table(
                summaries,
                columns=(
                    ("Citação inventada", "invented_citation_rate"),
                    ("Resposta inventada", "hallucinated_answer_rate"),
                    ("Erro de contrato", "response_contract_error_rate"),
                ),
            ),
        ]
    if task == "fiscal_extraction":
        return _fiscal_extras(summaries)
    if task == "ticket_routing":
        return [
            "<h3>Desempenho de classificação</h3>",
            _rate_table(
                summaries,
                columns=(
                    ("F1 macro", "macro_f1"),
                    ("Acurácia", "accuracy"),
                    ("Rótulo inválido", "invalid_label_rate"),
                ),
            ),
        ]
    if task == "regional_ptbr":
        return [
            "<h3>Validade da saída</h3>",
            _rate_table(
                summaries,
                columns=(("Resposta fora do formato", "invalid_answer_rate"),),
            ),
        ]
    return []


def _fiscal_extras(summaries: Sequence[ConfigSummary]) -> list[str]:
    fields = sorted({name for s in summaries for name in s.extra.get("field_accuracy", {})})
    if not fields:
        return []
    header = [_th("Campo"), *(_th(s.key.label, numeric=True) for s in summaries)]
    rows: list[str] = []
    for field_name in fields:
        cells = "".join(
            _td(_pct(s.extra.get("field_accuracy", {}).get(field_name, 0.0)), numeric=True)
            for s in summaries
        )
        rows.append(f"<tr>{_td(field_name)}{cells}</tr>")
    totals = "".join(
        _td(
            f"<strong>{_pct(s.extra.get('all_fields_correct_rate', 0.0))}</strong>",
            numeric=True,
            raw=True,
        )
        for s in summaries
    )
    rows.append(f"<tr><td><strong>Documento inteiro correto</strong></td>{totals}</tr>")
    return [
        "<h3>Acurácia por campo</h3>",
        f'<p class="note">{_esc(_FISCAL_NOTE)}</p>',
        _table(header, rows),
    ]


def _sensitivity_section(context: ReportContext) -> str:
    header = [
        _th("Tarefa"),
        _th("Modelo"),
        _th("De"),
        _th("Para"),
        _th("Qualidade", numeric=True),
        _th("Delta", numeric=True),
        _th("IC 95% do delta", numeric=True),
        _th("Significativo"),
        _th("Efeito injetado", numeric=True),
    ]
    rows: list[str] = []
    for c in context.sensitivity:
        rows.append(
            "<tr>"
            + _td(c.task)
            + _td(c.model + (" (simulado)" if c.provider == "simulation" else ""))
            + _td(c.prompt_a)
            + _td(c.prompt_b)
            + _td(f"{_pct(c.quality_a.point)} → {_pct(c.quality_b.point)}", numeric=True)
            + _td(f"{c.delta * 100:+.1f} pp", numeric=True)
            + _td(
                (
                    f"[{c.paired_delta.lower * 100:+.1f}, {c.paired_delta.upper * 100:+.1f}] pp"
                    if c.paired_delta is not None
                    else "n/d"
                ),
                numeric=True,
            )
            + _td("sim" if c.significant else "não")
            + _td(
                f"{c.injected_delta * 100:+.1f} pp" if c.injected_delta is not None else "n/d",
                numeric=True,
            )
            + "</tr>"
        )
    simulated = [c for c in context.sensitivity if c.injected_delta is not None]
    power_note = ""
    if simulated:
        detected = sum(c.significant for c in simulated)
        power_note = (
            '<p class="calibration-banner"><strong>Controle positivo / análise de poder.</strong> '
            "O simulador injeta até +3,5 pp na probabilidade de resposta correta; a tabela "
            "mostra o valor efetivo após o teto do perfil. "
            f"{detected}/{len(simulated)} efeitos foram detectados "
            "com IC 95% excluindo zero. Os demais delimitam a sensibilidade do desenho atual.</p>"
        )
    return (
        '<section><div class="section-head"><div><p class="section-kicker">Prompt effect</p>'
        "<h2>Sensibilidade a prompt</h2></div>"
        f'<p class="note">{_esc(_SENSITIVITY_NOTE)}</p></div>'
        + power_note
        + _table(header, rows)
        + "</section>"
    )


def _reading_section(context: ReportContext) -> str:
    parts = [
        '<section id="methodology">',
        '<div class="section-head"><div><p class="section-kicker">Measurement contract</p>'
        "<h2>Como ler os números</h2></div>"
        '<p class="note">O relatório deixa explícito o que foi medido, a unidade estatística '
        "e o que ainda não pode ser afirmado.</p></div>",
        '<div class="reading-grid">'
        f'<div class="reading-card"><b>Incerteza</b><p>{_esc(_READING_1)}</p></div>'
        f'<div class="reading-card"><b>Variância</b><p>{_esc(_READING_2)}</p></div>'
        f'<div class="reading-card"><b>Juiz</b><p>{_esc(_NO_JUDGE)}</p></div>'
        "</div>",
    ]
    if context.publication.checks:
        header = [_th("Gate"), _th("Estado"), _th("Evidência")]
        rows = [
            "<tr>"
            + _td(check.label)
            + _td("passou" if check.passed else "bloqueado")
            + _td(check.detail)
            + "</tr>"
            for check in context.publication.checks
        ]
        gate_title = (
            "Portões de calibração executados"
            if context.publication.status == "calibration"
            else "Portões de publicação executados"
        )
        parts.append(f"<h3>{gate_title}</h3>")
        parts.append(_table(header, rows))
    if context.judge_validations:
        header = [
            _th("Tarefa"),
            _th("Juiz"),
            _th("Amostra", numeric=True),
            _th("Kappa", numeric=True),
            _th("Interpretação"),
            _th("Aceito"),
        ]
        rows = [
            "<tr>"
            + _td(v.task)
            + _td(v.judge)
            + _td(str(v.sample_size), numeric=True)
            + _td(f"{v.kappa:.3f}", numeric=True)
            + _td(v.interpretation)
            + _td("sim" if v.accepted else "não")
            + "</tr>"
            for v in context.judge_validations
        ]
        parts.append("<h3>Validação de juiz automático</h3>")
        parts.append(_table(header, rows))
    else:
        parts.append('<p class="caution">Nenhum juiz automático foi usado nesta publicação.</p>')

    header = [
        _th("Tarefa"),
        _th("Itens", numeric=True),
        _th("Famílias semânticas", numeric=True),
        _th("Hash"),
    ]
    rows = [
        "<tr>"
        + _td(task.name)
        + _td(str(context.dataset_sizes.get(task.name, 0)), numeric=True)
        + _td(str(context.dataset_families.get(task.name, 0)), numeric=True)
        + _td(f"<code>{_esc(context.dataset_hashes.get(task.name, 'n/d')[:16])}</code>", raw=True)
        + "</tr>"
        for task in context.tasks
    ]
    parts.append("<h3>Proveniência dos datasets</h3>")
    parts.append(_table(header, rows))
    parts.append("</section>")
    return "".join(parts)


def _pareto_svg(points: Sequence[ParetoPoint], frontier: Sequence[ParetoPoint]) -> str:
    width, height = 900, 420
    left, right, top, bottom = 70, 30, 24, 60
    plot_w = width - left - right
    plot_h = height - top - bottom

    if not points:
        return (
            '<figure><svg viewBox="0 0 900 120" role="img" aria-label="Sem dados">'
            '<text x="20" y="60" fill="#8d9aad">Nenhuma rodada encontrada.</text></svg></figure>'
        )

    max_cost = max(p.cost_per_item_usd for p in points)
    max_cost = max_cost * 1.15 if max_cost > 0 else 0.001

    def x_of(cost: float) -> float:
        return left + (cost / max_cost) * plot_w

    def y_of(quality: float) -> float:
        return top + (1 - quality) * plot_h

    out: list[str] = [
        "<figure>",
        f'<svg viewBox="0 0 {width} {height}" role="img" aria-label="Gráfico de qualidade '
        'contra custo por item, com fronteira de Pareto destacada">',
    ]
    for tick in (0.0, 0.25, 0.5, 0.75, 1.0):
        y = y_of(tick)
        out.append(
            f'<line x1="{left}" y1="{y:.1f}" x2="{width - right}" y2="{y:.1f}" '
            'stroke="rgba(148,163,184,.16)" stroke-width="1"/>'
        )
        out.append(
            f'<text x="{left - 10}" y="{y + 4:.1f}" text-anchor="end" font-size="12" '
            f'fill="#8d9aad">{int(tick * 100)}%</text>'
        )
    axis_y = top + plot_h
    out.append(
        f'<line x1="{left}" y1="{axis_y}" x2="{width - right}" y2="{axis_y}" '
        'stroke="#5f6c7e" stroke-width="1.5"/>'
    )
    for index in range(5):
        cost = max_cost * index / 4
        out.append(
            f'<text x="{x_of(cost):.1f}" y="{axis_y + 20}" text-anchor="middle" font-size="12" '
            f'fill="#8d9aad">${cost:.4f}</text>'
        )
    out.append(
        f'<text x="{left + plot_w / 2:.1f}" y="{height - 14}" text-anchor="middle" '
        'font-size="13" fill="#8d9aad">Custo por item (USD)</text>'
    )
    out.append(
        f'<text transform="translate(18 {top + plot_h / 2:.1f}) rotate(-90)" '
        'text-anchor="middle" font-size="13" fill="#8d9aad">Qualidade média</text>'
    )

    ordered = sorted(frontier, key=lambda p: p.cost_per_item_usd)
    if len(ordered) > 1:
        path = " ".join(
            f"{'M' if i == 0 else 'L'} {x_of(p.cost_per_item_usd):.1f} {y_of(p.quality):.1f}"
            for i, p in enumerate(ordered)
        )
        out.append(
            f'<path d="{path}" fill="none" stroke="#36e4da" stroke-width="2" '
            'stroke-dasharray="4 3"/>'
        )

    frontier_labels = {p.label for p in frontier}
    occupied: dict[tuple[int, int], int] = {}
    for point in sorted(points, key=lambda p: p.label):
        cell = (round(x_of(point.cost_per_item_usd)), round(y_of(point.quality)))
        stack = occupied.get(cell, 0)
        occupied[cell] = stack + 1
        out.append(
            _point_svg(
                point,
                x_of,
                y_of,
                on_frontier=point.label in frontier_labels,
                label_offset=stack * 15,
            )
        )
    out.append("</svg>")
    out.append(f"<figcaption>{_esc(_FIGCAPTION)}</figcaption>")
    out.append("</figure>")
    return "".join(out)


def _point_svg(
    point: ParetoPoint,
    x_of: Callable[[float], float],
    y_of: Callable[[float], float],
    *,
    on_frontier: bool,
    label_offset: int = 0,
) -> str:
    """Um ponto e, se estiver na fronteira, seu rótulo.

    Pontos que caem na mesma posição recebem rótulos empilhados para cima,
    em vez de se sobreporem.
    """
    x, y = x_of(point.cost_per_item_usd), y_of(point.quality)
    title = _esc(
        f"{point.label}: {point.quality * 100:.1f}% qualidade, "
        f"${point.cost_per_item_usd:.5f} por item, p95 {point.latency_p95_ms:.0f} ms"
    )
    if not on_frontier:
        return (
            f'<circle cx="{x:.1f}" cy="{y:.1f}" r="6" fill="#0c1018" stroke="#5f6c7e" '
            f'stroke-width="2"><title>{title}</title></circle>'
        )
    anchor = "start" if x < 650 else "end"
    dx = 12 if anchor == "start" else -12
    return (
        f'<circle cx="{x:.1f}" cy="{y:.1f}" r="7" fill="#36e4da"><title>{title}</title></circle>'
        f'<text x="{x + dx:.1f}" y="{y - 10 - label_offset:.1f}" text-anchor="{anchor}" '
        f'font-size="12" font-weight="600" fill="#f4f7fb">{_esc(point.label)}</text>'
    )
