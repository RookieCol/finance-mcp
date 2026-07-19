"""Scheduler job bodies — plain functions taking a Session and a
Notifier, invoked directly by tests (no live clock needed) and wired to
APScheduler triggers in ``runner.py``.
"""

from datetime import date

from sqlalchemy.orm import Session

from caudal.core import alerts, projections, reporting
from caudal.core.logging import get_logger
from caudal.scheduler.notifier import Notifier

logger = get_logger(__name__)


def run_alert_check(
    session: Session, notifier: Notifier, *, cash_balance_minor: int = 0, as_of: date | None = None
) -> list[alerts.AlertFinding]:
    """Runs the proactive alert rules and delivers any newly-fired
    finding. Idempotent: `core.alerts.evaluate_alerts` already dedupes
    against `AlertEvent.dedup_key`, so running this job twice for the
    same day/condition sends nothing the second time.
    """
    findings = alerts.evaluate_alerts(session, cash_balance_minor=cash_balance_minor, as_of=as_of)
    for finding in findings:
        notifier.send(
            title=f"[{finding.severity.value.upper()}] {finding.rule}",
            body=_format_payload(finding.payload),
        )
    logger.info("scheduler.alert_check_run", new_alerts=len(findings))
    return findings


def run_weekly_digest(session: Session, notifier: Notifier, *, cash_balance_minor: int = 0) -> str:
    """Builds and delivers the weekly digest: totals, projection
    snapshot. Always sends (a digest with "nothing changed" is still
    useful proactive signal, unlike alerts which are dedup'd by design).
    """
    month_totals = reporting.totals_by_month(session)
    category_totals = reporting.totals_by_category(session)
    proj = projections.compute_projections(session, cash_balance_minor=cash_balance_minor)

    lines = ["Weekly finance digest", ""]
    lines.append("Totals by category (all time):")
    for cat_row in category_totals:
        lines.append(f"  {cat_row.category}: {cat_row.currency} {cat_row.total_minor / 100:.2f}")
    lines.append("")
    lines.append("Totals by month:")
    for month_row in month_totals:
        lines.append(f"  {month_row.month}: {month_row.currency} {month_row.total_minor / 100:.2f}")
    lines.append("")
    if proj.runway_months:
        lines.append(f"Runway: {proj.runway_months:.1f} months")
    else:
        lines.append("Runway: n/a")
    if proj.mrr_growth_rate is not None:
        lines.append(f"MRR growth: {proj.mrr_growth_rate * 100:.1f}%")

    body = "\n".join(lines)
    notifier.send(title="Weekly finance digest", body=body)
    logger.info("scheduler.digest_run")
    return body


def _format_payload(payload: dict[str, object]) -> str:
    return ", ".join(f"{k}={v}" for k, v in payload.items())
