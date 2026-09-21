# Threat model

## Scope

Benchmark e Harness de Avaliação PT-BR executes third-party model APIs against synthetic benchmark inputs, stores raw outputs locally and publishes aggregate static reports. It does not process production customer data and is not an online inference service.

## Assets

- provider API credentials;
- private holdout items;
- raw model outputs and run metadata;
- integrity of scorers, datasets and published results;
- maintainer and contributor supply chain.

## Trust boundaries

| Boundary | Main risk | Control |
|---|---|---|
| CLI → provider API | Credential exposure, interception, malicious response | Environment-only secrets, TLS client, timeouts, bounded response handling |
| Provider response → parser | Malformed or adversarial output | Task parser validation; failure becomes explicit zero-scored observation |
| Dataset → model prompt | Prompt injection inside evidence text | Task instructions separate content from output contract; deterministic scorer remains authoritative |
| Local cache/results | Tampering or stale reuse | Content-addressed keys, run manifest, dataset and prompt hashes |
| Public dataset → future model | Benchmark contamination | Non-versioned private holdout and public/holdout comparison |
| Dependency supply chain | Vulnerable or compromised package | Frozen lockfile, minimal runtime dependencies, `pip-audit`, Dependabot |
| Report rendering | Stored HTML/script injection | HTML escaping, restrictive CSP, no external runtime dependency |

## Abuse cases

### Result laundering

An actor could publish a favorable subset, omit failed calls or combine incompatible dataset versions. Countermeasures: raw observations remain versioned; error rates are visible; report aggregation rejects conflicting hashes; the reproduction guide requires both prompts and all tasks.

### Cache poisoning

A response could be reused after a prompt or model changes. The cache key includes provider, exact model, rendered prompt and seed. Prompt content changes invalidate the entry.

### Cost denial of service

Misconfigured concurrency or retries can create unexpected API spend. Concurrency is bounded, retries are bounded, baseline calibration needs no API, and real-model execution is an explicit operator action. Provider budget caps remain an external operational requirement.

### Holdout disclosure

Publishing a holdout destroys its role in contamination detection. `holdout.jsonl` is Git-ignored; examples contain no private items. Reviewers must reject pull requests containing private split content.

### Misleading statistical claims

Surface variants could inflate N, prompt comparisons could ignore pairing, or a judge could score itself. Benchmark e Harness de Avaliação PT-BR clusters variants by semantic family, pairs prompt deltas, and refuses unvalidated judge claims by publication policy.

## Residual risks

- A compromised maintainer can still alter code and artifacts together.
- Provider model aliases may change behavior without changing the caller’s string.
- Client-side latency is influenced by network and provider queueing.
- Synthetic data cannot reproduce the full entropy of production inputs.
- A single-author gold set can encode systematic labeling bias.

Signed releases, independent annotation and external replication are recommended before high-stakes procurement decisions.
