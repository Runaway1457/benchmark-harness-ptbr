<div align="center">
  <img src="docs/assets/ptbr-benchmark-hero.svg" alt="Benchmark e Harness de Avaliação PT-BR" width="100%">
</div>

<h1 align="center">Benchmark e Harness de Avaliação PT-BR</h1>

<div align="center">
  <br>
  <a href=".github/workflows/ci.yml"><img alt="CI" src="https://img.shields.io/badge/CI-176%20tests-36e4da?style=flat-square"></a>
  <a href="tests/"><img alt="coverage" src="https://img.shields.io/badge/branch%20coverage-98.7%25-36e4da?style=flat-square"></a>
  <a href="tasks/"><img alt="dataset" src="https://img.shields.io/badge/public%20items-750-8b7bff?style=flat-square"></a>
  <a href="docs/methodology.md"><img alt="statistics" src="https://img.shields.io/badge/statistics-95%25%20clustered%20bootstrap-8b7bff?style=flat-square"></a>
  <a href="LICENSE"><img alt="license" src="https://img.shields.io/badge/license-Apache--2.0-f4f7fb?style=flat-square"></a>
</div>

<p align="center">
  A reproducible, provider-agnostic benchmark for choosing language models on Brazilian corporate tasks.<br>
  <strong>Quality, cost, latency, variance and prompt sensitivity—measured together.</strong>
</p>

<p align="center">
  <a href="site/index.html"><strong>Explore the report</strong></a>
  · <a href="docs/methodology.md">Methodology</a>
  · <a href="docs/dataset-card.md">Dataset card</a>
  · <a href="docs/results.md">Versioned results</a>
  · <a href="README.pt-BR.md">Português</a>
</p>

> [!IMPORTANT]
> The checked-in release is a **harness calibration**, not a vendor leaderboard. It contains the deterministic rules baseline so the entire measurement path can be audited without API keys. Real-provider claims are published only after the exact models complete all 750 items × 3 repetitions under the same dataset hashes.

## The decision this benchmark makes possible

“Which model is best?” is the wrong production question. This benchmark answers the one engineering teams actually face:

> Which model-and-prompt configuration meets the quality threshold for this PT-BR task at the lowest defensible cost and latency?

Most public leaderboards emphasize English, academic questions and a single aggregate score. This harness measures five operational tasks with Brazilian formats, language and regulation, then keeps uncertainty and unit economics visible instead of collapsing them into a vanity rank.

| Task | Operational failure being measured | Primary metric | Public items | Independent families |
|---|---|---:|---:|---:|
| Fiscal document extraction | Wrong CNPJ, total or invoice field | Weighted field accuracy + exact match | 150 | 150 |
| Support ticket routing | Ticket reaches the wrong queue | Macro F1 across 8 queues | 150 | 48 |
| LGPD refusal | Sensitive data leaks or legitimate work is blocked | Correct refusal; leak and over-refusal rates | 150 | 48 |
| Grounded internal QA | Answer or citation is invented | Groundedness + invented-citation rate | 150 | 42 |
| Regional PT-BR | Regional expression is misunderstood | Accuracy by language variant | 150 | 51 |

The 411 controlled surface variants stress formality, mobile-message noise and contextual framing. They are **not** treated as independent samples: confidence intervals resample the 339 semantic families, preventing pseudo-replication.

## Publication contract

Every number in a release must satisfy the same contract:

| Claim | Enforcement |
|---|---|
| Quality | Task-specific deterministic scorer; normalized to [0, 1] |
| Uncertainty | 95% percentile bootstrap over semantic families |
| Prompt effect | Paired bootstrap on the same semantic families |
| Stochasticity | 3 repetitions per item; disagreement and within-item variance |
| Cost | Mean cost of one inference, with measured vs estimated tokens separated |
| Latency | Client-side p50 and p95, errors excluded and reported separately |
| Judge validity | Human agreement must be recorded before judge scores are accepted |
| Provenance | Dataset SHA-256, prompt hash, model, seed and pricing snapshot in artifacts |
| Reproducibility | The same results directory produces byte-identical reports |

No judge-generated score is present in the current release. A future LLM judge must clear a predeclared Cohen’s kappa threshold against human annotations before it can enter a published result.

## Architecture

<div align="center">
  <img src="docs/assets/benchmark-architecture.svg" alt="PT-BR benchmark architecture from dataset commit to static report" width="100%">
</div>

The domain layer never imports an SDK. Each provider implements the same port and returns the same `Completion` contract. Tasks own request construction, parsing and scoring. The runner owns concurrency, retry/backoff, caching and raw observation persistence. Reports only consume versioned artifacts.

```text
TaskDefinition → CompletionRequest → Provider → Completion → deterministic score
        │                                  │
        └── dataset + prompt hashes        └── token use + latency + attempts
                                               │
                                               ▼
                                observations.jsonl + manifest.json
                                               │
                                   clustered statistical aggregation
                                               │
                              results.md + summary.json + static dashboard
```

Key design decisions are recorded as ADRs in [`docs/adr/`](docs/adr/):

- provider-agnostic HTTP boundaries;
- a judge cannot be trusted before human-agreement validation;
- reports are single-file, deterministic static artifacts;
- private holdouts are never committed;
- the rules baseline is a calibration control, not a competing model.

## Run the complete calibration

Prerequisites: Python 3.12+ and [uv](https://docs.astral.sh/uv/).

```bash
git clone <repository-url> benchmark-harness-ptbr
cd benchmark-harness-ptbr
uv sync --extra dev
make check
make run
python -m http.server 8000 --directory site
```

Open `http://localhost:8000`. `make run` validates all 750 public items, executes both prompt variants three times with the rules baseline, and regenerates every report artifact.

Run a real model without changing benchmark code:

```bash
export OPENAI_API_KEY="..."
uv run ptbr-benchmark run \
  --provider openai \
  --model YOUR_EXACT_MODEL_ID \
  --prompt optimized \
  --repetitions 3
uv run ptbr-benchmark report
```

Anthropic uses the same interface:

```bash
export ANTHROPIC_API_KEY="..."
uv run ptbr-benchmark run \
  --provider anthropic \
  --model YOUR_EXACT_MODEL_ID \
  --prompt optimized \
  --repetitions 3
```

Responses are cached by provider, exact model, rendered prompt and seed. A one-character prompt change produces a different cache key. Retryable 429, 5xx and timeout failures use exponential backoff with jitter; terminal failures remain visible as zero-scored error observations.

## Current calibration snapshot

The rules baseline is deliberately simple. Its purpose is to prove that task loading, parsing, scoring, uncertainty, reporting and provenance all execute end to end.

| Task | Baseline quality | What this validates |
|---|---:|---|
| Fiscal extraction | 96.6% | Brazilian field normalization and weighted scoring |
| Ticket routing | 77.3% macro F1 | Multiclass scoring and invalid-label handling |
| LGPD refusal | 72.9% | Leak vs over-refusal decomposition |
| Grounded QA | 43.7% | Citation and unanswerable-question failure modes |
| Regional PT-BR | 32.4% | Regional-language dataset and balanced choices |

These are **control results**, not evidence about any commercial model. Exact intervals, dataset hashes and timestamps live in [`docs/results.md`](docs/results.md).

## Repository map

```text
benchmark-harness-ptbr/
├── ptbr_benchmark/
│   ├── domain/          # immutable contracts and statistical primitives
│   ├── providers/       # provider port, HTTP adapters, pricing and cascade
│   ├── runner/          # execution, retry, concurrency and SQLite cache
│   ├── scoring/         # PT-BR normalization and task scorers
│   ├── tasks/           # task definitions and synthetic generators
│   └── report/          # deterministic Markdown, JSON and HTML builders
├── tasks/               # datasets, prompts and per-task documentation
├── results/             # versioned run manifests and raw observations
├── site/                # generated static decision dashboard
├── docs/                # methodology, dataset card, ADRs and release evidence
├── tests/               # domain, scoring, provider, runner, CLI and report tests
└── deployment/          # rootless image and hardened static-site server
```

## Quality gates

```bash
make check
```

The gate runs:

- Ruff formatting and lint;
- strict MyPy;
- Bandit static security analysis;
- `pip-audit` against a frozen export of runtime dependencies;
- 176 tests with branch-aware coverage (current snapshot: 98.7%);
- architecture tests against dead wiring and forbidden dependency directions;
- deterministic report tests that compare output hashes;
- provider fault tests for timeout, rate limit, truncation and malformed JSON.

CI repeats the suite on Python 3.12 and 3.13, runs a baseline E2E pipeline and uploads the generated site as an artifact. The security workflow runs on every pull request and weekly.

## Dataset and research limits

- All data is synthetic; no customer, person or company record was used.
- The 750 public items represent 339 independent semantic families. Surface variants improve robustness coverage but do not create independent evidence.
- Curated gold labels currently have one primary author; independent double annotation is a release gate for claims that depend on human judgment.
- The public split can become contaminated after publication. Private `holdout.jsonl` files are supported and excluded from Git.
- Client-side latency includes network and provider queueing. Compare configurations collected in the same run window.
- Pricing is versioned by date and must be reviewed before every public model matrix.

Read the full [methodology](docs/methodology.md), [dataset card](docs/dataset-card.md), [threat model](docs/threat-model.md) and [reproduction guide](docs/reproduction.md) before interpreting a result.

## Contributing

Contributions are accepted only when they preserve the measurement contract. New datasets require provenance and family IDs; new providers require fault-injection tests; new metrics require edge-case fixtures; new judges require recorded human agreement.

See [CONTRIBUTING.md](CONTRIBUTING.md) and [SECURITY.md](SECURITY.md).

## Citation

```bibtex
@software{ptbrbenchmark2026,
  title  = {Benchmark and Evaluation Harness for Brazilian Portuguese Corporate LLM Tasks},
  author = {Borges, Gabriel},
  year   = {2026},
  license = {Apache-2.0}
}
```

## Maintainer

Designed and maintained by **Gabriel Borges**. Benchmark claims are backed by versioned datasets, executable scorers and reproducible run artifacts—not by narrative.

Apache-2.0 licensed.
