# Contributing

This is a single-maintainer project run for one SaaS's internal finances, so this file stays short — it documents the two conventions that keep the history and CI meaningful, not a full external-contributor process.

## Commits

Follow [Conventional Commits](https://www.conventionalcommits.org/): `type(scope): summary`, e.g. `feat(core): add projection engine`, `fix(mcp): handle missing currency in record_transaction`. Enforced locally via `commitizen` (`cz commit`) and checked in CI. This is what drives the changelog and semantic version bumps — it's not just style.

## CI gates

Every push/PR runs, in order: lint (`ruff`) → type-check (`mypy`) → security scans (`bandit`, `pip-audit`, `gitleaks`) → Dockerfile lint (`hadolint`) → tests (`pytest`, real Postgres via `testcontainers`) → coverage gate. All must pass before merging to `main`. See `.github/workflows/ci.yml` once Stage 9 lands.
