# Release gates

| Gate | Calibration | Public model matrix |
|---|:---:|:---:|
| 750 public items validate | required | required |
| Dataset hashes consistent | required | required |
| Rules baseline completes | required | required |
| Two prompt variants | required | required |
| Three repetitions | required | required |
| Exact model IDs recorded | n/a | required |
| Pricing snapshot no earlier than the measured runs | n/a | required |
| ≥2 real model configurations | n/a | required |
| Judge agreement artifact | if used | if used |
| Private holdout comparison | recommended | required for generalization claim |
| Full quality/security suite | required | required |
| Byte-stable reports | required | required |

The dashboard must display “calibration” until the public-model gates are met.

## Executable enforcement

`ptbr-benchmark report` evaluates these gates from the versioned manifests and
raw observations. A real-provider run starts in `pre-publication`; only a full
matrix with two explicit provider/model configurations, two prompts, three
observations per item, complete task coverage, current pricing and provider
error rate at or below 2% can become `published`. The decision and every check
are written to `site/summary.json` under `publication_gates`.

Failed configurations never enter the Pareto surface. They remain visible in
task diagnostics with their error rate and exclusion reason.
