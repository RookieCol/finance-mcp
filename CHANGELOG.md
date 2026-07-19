# Changelog

All notable changes to this project are documented here. Entries are written **with** the change, not after it. The *why* behind significant decisions lives in [`docs/adr/`](docs/adr/).

Format: [Keep a Changelog](https://keepachangelog.com/en/1.1.0/) · versioning: [SemVer](https://semver.org/) (pre-1.0: minor = feature milestone).

## [Unreleased]

- **Phase 01 — Revenue**: clients, plans, subscriptions, invoices/AR (cartera), `payroll` category, real MRR from subscriptions. See [`planning/01-revenue.md`](planning/01-revenue.md).

## [0.2.0] — 2026-07-19

### Added
- **Automatic USD→COP conversion** at the official daily TRM (Banco de la República via datos.gov.co) applied at record time in both the web form and the MCP `record_transaction` tool (`core/fx.py`). If the rate is unavailable the transaction is rejected with a clear error — never silently stored in USD.
- **Projections page** (`/projections`): forecast table plus the full assumptions panel (trend window, months used, recurring income/expense) that previously was only reachable via MCP.
- **Reports page** (`/reports`): net cash flow by month, month-over-month delta, expense/income category breakdowns, date-range filtering.
- **Budget management**: inline limit editing and active/inactive toggle (`repository.update_budget`).
- **Dashboard**: hero card with net-this-month and a 12-segment runway meter, per-vendor infra breakdown for the current month, expense breakdown sorted by size with share-of-total bars.
- **Human-readable alert payloads** (per-rule formatting; raw dict behind a `<details>`).
- Human-readable category labels across the UI alongside the raw accounting keys.
- Planning roadmap under [`planning/`](planning/) (revenue, AI & automation, remote access).

### Changed
- **Complete UI redesign** ("Vertex"): monochrome design system in a static stylesheet (Geist/Geist Mono, light/dark via tokens), pill navigation on desktop, fixed bottom-tab navigation on mobile, server-side SVG charts in Python (`web/charts.py`) — still zero JS frameworks, zero build step.
- Dashboard month breakdowns cover the full calendar month (a payment recorded for the 30th is part of "this month"), consistent with the hero.
- `web` compose service now receives `SCHEDULER_CASH_BALANCE`, so the dashboard runway uses the configured cash balance.

### Fixed
- **Net cash flow had no sign**: monthly history summed income and expense magnitudes together, so an all-expense month charted as positive. `reporting.net_totals_by_month` now computes signed income − expense (dashboard, projections, reports).
- **Recurring forecast base double-counted streams**: the base summed every recurring transaction ever recorded, inflating a little more each month. It now uses each category's most recent month (`reporting.latest_recurring_totals_by_category`) and self-corrects as new payments land. See [ADR-0008](docs/adr/0008-recurring-base-latest-month.md).
- CSS grid columns no longer collapse when a sibling card contains long unbreakable content (`minmax(0, 1fr)`).

## [0.1.0] — 2026-07-19

Initial platform. MCP server (8 tools, stdio) with elicitation for ambiguous input; shared `core/` domain layer (validation, idempotent audited repository, reporting, deterministic projections, deduplicated alert rules); internal FastAPI/Jinja2 UI; APScheduler-based proactive digests and alerts with webhook delivery; structured logging, OpenTelemetry tracing, Prometheus metrics; CI (lint, types, SAST, dependency audit, secrets scan, tests at an 85% coverage gate against real Postgres via testcontainers); Docker Compose deployment with daily backups and a tested restore path; Hermes dev-chat integration profile.

[Unreleased]: https://github.com/RookieCol/caudal/compare/v0.2.0...HEAD
[0.2.0]: https://github.com/RookieCol/caudal/compare/v0.1.0...v0.2.0
[0.1.0]: https://github.com/RookieCol/caudal/releases/tag/v0.1.0
