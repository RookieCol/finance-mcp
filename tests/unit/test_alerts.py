from finance_mcp.core.alerts import (
    BUDGET_CRITICAL_THRESHOLD,
    BUDGET_WARNING_THRESHOLD,
    budget_overrun_findings,
    missing_recurring_income_finding,
    runway_threshold_finding,
    spend_spike_findings,
)
from finance_mcp.core.models import AlertSeverity
from finance_mcp.core.reporting import CategoryTotal


def test_budget_overrun_fires_warning_at_80_percent() -> None:
    spend = [CategoryTotal(category="marketing", currency="USD", total_minor=800)]
    findings = budget_overrun_findings(spend, {"marketing": 1000})
    assert len(findings) == 1
    assert findings[0].severity == AlertSeverity.warning
    assert findings[0].payload["ratio"] == BUDGET_WARNING_THRESHOLD


def test_budget_overrun_fires_critical_at_100_percent() -> None:
    spend = [CategoryTotal(category="marketing", currency="USD", total_minor=1000)]
    findings = budget_overrun_findings(spend, {"marketing": 1000})
    assert findings[0].severity == AlertSeverity.critical
    assert findings[0].payload["ratio"] == BUDGET_CRITICAL_THRESHOLD


def test_budget_overrun_silent_below_warning_threshold() -> None:
    spend = [CategoryTotal(category="marketing", currency="USD", total_minor=799)]
    findings = budget_overrun_findings(spend, {"marketing": 1000})
    assert findings == []


def test_budget_overrun_ignores_categories_without_a_budget() -> None:
    spend = [CategoryTotal(category="rd", currency="USD", total_minor=999999)]
    assert budget_overrun_findings(spend, {"marketing": 1000}) == []


def test_spend_spike_fires_when_over_1_5x_trailing_average() -> None:
    current = [CategoryTotal(category="marketing", currency="USD", total_minor=1600)]
    findings = spend_spike_findings(current, {"marketing": 1000.0})
    assert len(findings) == 1
    assert findings[0].rule == "spend_spike"


def test_spend_spike_silent_at_exactly_1_5x() -> None:
    current = [CategoryTotal(category="marketing", currency="USD", total_minor=1500)]
    assert spend_spike_findings(current, {"marketing": 1000.0}) == []


def test_runway_threshold_silent_when_above_warning_months() -> None:
    assert runway_threshold_finding(12.0, warning_months=6.0) is None


def test_runway_threshold_warning_below_threshold() -> None:
    finding = runway_threshold_finding(5.0, warning_months=6.0)
    assert finding is not None
    assert finding.severity == AlertSeverity.warning


def test_runway_threshold_critical_below_half_threshold() -> None:
    finding = runway_threshold_finding(2.0, warning_months=6.0)
    assert finding is not None
    assert finding.severity == AlertSeverity.critical


def test_runway_threshold_silent_when_runway_is_infinite() -> None:
    assert runway_threshold_finding(None) is None


def test_missing_recurring_income_detects_gap() -> None:
    finding = missing_recurring_income_finding(
        expected_categories={"subscription"}, seen_this_month_categories=set()
    )
    assert finding is not None
    assert finding.payload["missing_categories"] == ["subscription"]


def test_missing_recurring_income_silent_when_all_present() -> None:
    finding = missing_recurring_income_finding(
        expected_categories={"subscription"}, seen_this_month_categories={"subscription"}
    )
    assert finding is None
