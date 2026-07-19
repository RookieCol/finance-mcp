# 0007 — Server-rendered UI with no build step

**Status:** Accepted · **Date:** 2026-07-19

## Context

The internal UI needed a full redesign (design system, charts, mobile navigation). The default industry answer — React + component library + bundler — would add a Node toolchain, a build pipeline, and a JSON API layer to a single-user internal tool maintained by one person.

## Decision

Stay server-rendered: Jinja2 templates, one hand-written stylesheet of design tokens and components (`web/static/app.css`), and charts generated **server-side as inline SVG by Python** (`web/charts.py`) styled via CSS variables so they follow light/dark automatically. Zero JS frameworks, zero build step; the only JavaScript is inline `confirm()` on destructive actions. Rejected: React/shadcn + Vite — authentic component library, but it would have required building an entire JSON API surface that nothing else needs.

## Consequences

The UI ships inside the Python package (templates and static files travel with `uv` packaging; the Dockerfile needed no changes), works with JS disabled, and chart geometry is unit-testable Python instead of browser code. Mobile app-feel comes from CSS alone (fixed bottom tab bar). Trade-off accepted: no client-side interactivity beyond forms — if the tool ever needs live updates or optimistic UI, this decision gets revisited rather than fought.
