# Changelog

## 0.2.0

Calibration release with a publication-grade measurement contract.

- 750 public items across five tasks; 339 independent semantic families.
- Clustered 95% bootstrap intervals prevent surface variants from inflating N.
- Ticket routing uses macro F1; prompt sensitivity uses paired bootstrap.
- Cost is reported per inference, not multiplied by repetitions.
- Missing model pricing fails closed; missing token usage is marked as estimated.
- Advanced self-contained decision dashboard with sortable tables and Pareto view.
- International README, architecture assets, threat model and reproduction gates.
- Deterministic baseline calibration across 4,500 observations.

## 0.1.0

Primeira publicação.

- Cinco tarefas: extração fiscal, roteamento de ticket, recusa LGPD, QA com
  citação, português regional.
- Provedores Anthropic e OpenAI por HTTP, baseline por regras, cascata.
- Cache SQLite endereçado por conteúdo, retry com backoff e jitter.
- Relatório Markdown e site estático determinístico com fronteira de Pareto.
- Validação de juiz por kappa de Cohen.
- 339 itens públicos; holdout local não versionado.
