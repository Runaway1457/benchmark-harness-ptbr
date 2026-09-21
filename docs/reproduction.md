# Reproduction guide

This guide reproduces the checked-in calibration without paid APIs and defines the evidence required for a real-model release.

## Environment

- Linux or macOS;
- Python 3.12 or 3.13;
- uv with the committed `uv.lock`;
- no network access is required for the baseline after dependencies are installed.

## Baseline calibration

```bash
uv sync --frozen --extra dev
uv run ptbr-benchmark validate
uv run ptbr-benchmark run --provider baseline --prompt minimal --repetitions 3 --no-cache
uv run ptbr-benchmark run --provider baseline --prompt optimized --repetitions 3 --no-cache
uv run ptbr-benchmark report
make check
```

Expected dataset inventory:

| Task | Items | Families |
|---|---:|---:|
| `fiscal_extraction` | 150 | 150 |
| `ticket_routing` | 150 | 48 |
| `lgpd_refusal` | 150 | 48 |
| `grounded_qa` | 150 | 42 |
| `regional_ptbr` | 150 | 51 |

The generated files are:

- `results/<run-id>/manifest.json` — immutable run configuration and dataset hashes;
- `results/<run-id>/observations.jsonl` — raw completion, score, usage and latency while running;
- `results/<run-id>/observations.jsonl.gz` — deterministic compressed form accepted for versioned releases;
- `docs/results.md` — reviewable result narrative;
- `site/summary.json` — machine-readable aggregates;
- `site/index.html` — self-contained decision dashboard.

## Determinism check

Generate the report twice without changing `results/` and compare:

```bash
sha256sum docs/results.md site/index.html site/summary.json
uv run ptbr-benchmark report
sha256sum docs/results.md site/index.html site/summary.json
```

All three hashes must remain unchanged.

## Real-model release

For each exact model ID and both prompt variants:

```bash
uv run ptbr-benchmark run \
  --provider PROVIDER \
  --model EXACT_MODEL_ID \
  --prompt PROMPT \
  --repetitions 3 \
  --no-cache
```

Run all models in the same region and time window. Record:

- exact model ID returned by the provider;
- provider and client region;
- start/end timestamps;
- pricing source and reference date;
- any provider-side sampling controls;
- dataset and prompt hashes;
- terminal errors and retry counts.

Do not merge results from different dataset hashes. Do not publish a judge-based metric before its human-agreement artifact is present.

## Release acceptance

A release is publishable only when:

- all five tasks contain at least 150 public items;
- every model/prompt pair has three repetitions;
- dataset hashes agree across all included runs;
- both prompt variants completed for every model;
- pricing is reviewed for the publication date;
- no unexpected terminal-error cluster remains unexplained;
- `make check` passes from a clean clone;
- report artifacts are byte-stable;
- limitations and calibration/publication state are accurate.
