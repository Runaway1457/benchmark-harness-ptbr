# Security policy

## Supported versions

Security fixes are applied to the latest minor release on the default branch.

## Reporting a vulnerability

Do not open a public issue for credentials, holdout disclosure, arbitrary code execution, dependency compromise or a flaw that can falsify published results. Use GitHub’s private vulnerability reporting for the repository.

Include:

- affected version or commit;
- minimal reproduction;
- expected and observed behavior;
- impact on confidentiality, integrity, availability or benchmark validity;
- suggested mitigation, if known.

Never include a real API key, customer record or private holdout item.

## Secrets

Provider keys are read from environment variables and must not be committed. `.env`, caches and private holdouts are ignored. Rotate any credential that appears in a log, artifact, issue or commit history.

## Scope boundary

Benchmark e Harness de Avaliação PT-BR is a benchmark harness, not a production data-processing service. Running it on proprietary data changes the threat model and requires organization-specific access controls, retention policy and privacy review.
