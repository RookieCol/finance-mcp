"""Proactive alert rule engine — evaluated by the scheduler (Stage 7) or
the `check_alerts` MCP tool (Stage 4), never as a side effect of a normal
read.

Each rule is a pure function over already-fetched data (unit-testable
against fixtures), plus an orchestrator that ties rules to the DB and
handles dedup via ``AlertEvent.dedup_key`` — a rule that already has an
open event for the same finding does not fire again until the finding
resolves.
"""

from dataclasses import dataclass
from datetime import date

from sqlalchemy.orm import Session

from finance_mcp.core import projections, reporting
from finance_mcp.core.models import AlertSeverity, TransactionType
from finance_mcp.core.reporting import CategoryTotal
from finance_mcp.core.repository import (
    create_alert_event,
    delete_alert_event,
    get_open_alert,
    list_active_budgets,
    list_open_alerts_for_rules,
)

BUDGET_WARNING_THRESHOLD = 0.8
BUDGET_CRITICAL_THRESHOLD = 1.0
SPEND_SPIKE_FACTOR = 1.5
DEFAULT_RUNWAY_WARNING_MONTHS = 6.0

DEDUP_TRACKED_RULES = ("budget_overrun", "runway_threshold")


@dataclass(frozen=True)
class AlertFinding:
    rule: str
    severity: AlertSeverity
    dedup_key: str
    payload: dict[str, object]


# --- Pure rules --------------------------------------------------------


def budget_overrun_findings(
    spend_by_category: list[CategoryTotal], monthly_limits_minor: dict[str, int]
) -> list[AlertFinding]:
    findings = []
    for row in spend_by_category:
        limit = monthly_limits_minor.get(row.category)
        if limit is None or limit <= 0:
            continue
        ratio = row.total_minor / limit
        if ratio >= BUDGET_CRITICAL_THRESHOLD:
            severity = AlertSeverity.critical
        elif ratio >= BUDGET_WARNING_THRESHOLD:
            severity = AlertSeverity.warning
        else:
            continue
        findings.append(
            AlertFinding(
                rule="budget_overrun",
                severity=severity,
                dedup_key=f"budget_overrun:{row.category}:{row.currency}",
                payload={
                    "category": row.category,
                    "currency": row.currency,
                    "spend_minor": row.total_minor,
                    "limit_minor": limit,
                    "ratio": ratio,
                },
            )
        )
    return findings


def spend_spike_findings(
    current_month: list[CategoryTotal], trailing_average_minor: dict[str, float]
) -> list[AlertFinding]:
    findings = []
    for row in current_month:
        avg = trailing_average_minor.get(row.category)
        if not avg or avg <= 0:
            continue
        if row.total_minor > avg * SPEND_SPIKE_FACTOR:
            findings.append(
                AlertFinding(
                    rule="spend_spike",
                    severity=AlertSeverity.warning,
                    dedup_key=f"spend_spike:{row.category}:{row.currency}",
                    payload={
                        "category": row.category,
                        "currency": row.currency,
                        "current_minor": row.total_minor,
                        "trailing_average_minor": avg,
                    },
                )
            )
    return findings


def runway_threshold_finding(
    runway: float | None, warning_months: float = DEFAULT_RUNWAY_WARNING_MONTHS
) -> AlertFinding | None:
    if runway is None:
        return None
    if runway >= warning_months:
        return None
    severity = AlertSeverity.critical if runway < warning_months / 2 else AlertSeverity.warning
    return AlertFinding(
        rule="runway_threshold",
        severity=severity,
        dedup_key="runway_threshold",
        payload={"runway_months": runway, "warning_months": warning_months},
    )


def missing_recurring_income_finding(
    expected_categories: set[str], seen_this_month_categories: set[str]
) -> AlertFinding | None:
    missing = sorted(expected_categories - seen_this_month_categories)
    if not missing:
        return None
    return AlertFinding(
        rule="missing_recurring_income",
        severity=AlertSeverity.warning,
        dedup_key=f"missing_recurring_income:{','.join(missing)}",
        payload={"missing_categories": missing},
    )


# --- Orchestration -----------------------------------------------------


def evaluate_alerts(
    session: Session, *, cash_balance_minor: int = 0, as_of: date | None = None
) -> list[AlertFinding]:
    """Runs every dedup-tracked rule, persists genuinely new findings
    (skipping ones with an already-open dedup_key), and clears dedup keys
    for findings that no longer reproduce (the condition resolved).
    Returns only the newly-created findings for this run.
    """
    as_of = as_of or date.today()
    new_findings: list[AlertFinding] = []
    still_firing_keys: set[str] = set()

    budgets = {b.category: b.monthly_limit_minor for b in list_active_budgets(session)}
    month_start = as_of.replace(day=1)
    current_spend = reporting.totals_by_category(
        session, type=TransactionType.expense, date_from=month_start, date_to=as_of
    )
    budget_findings = budget_overrun_findings(current_spend, budgets)

    proj = projections.compute_projections(
        session, cash_balance_minor=cash_balance_minor, as_of=as_of
    )
    runway_finding = runway_threshold_finding(proj.runway_months)

    for finding in [*budget_findings, *([runway_finding] if runway_finding else [])]:
        still_firing_keys.add(finding.dedup_key)
        if get_open_alert(session, finding.dedup_key) is None:
            create_alert_event(
                session,
                rule=finding.rule,
                severity=finding.severity,
                payload=finding.payload,
                dedup_key=finding.dedup_key,
            )
            new_findings.append(finding)

    # Resolve alerts whose condition no longer holds, so a genuine future
    # breach isn't swallowed by a stale dedup entry.
    for open_alert in list_open_alerts_for_rules(session, DEDUP_TRACKED_RULES):
        if open_alert.dedup_key not in still_firing_keys:
            delete_alert_event(session, open_alert.dedup_key)

    return new_findings
