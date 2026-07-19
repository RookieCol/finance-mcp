from caudal.core.reporting import MonthTotal, month_over_month_delta


def test_month_over_month_delta_hand_computed() -> None:
    current = [
        MonthTotal(month="2026-06", currency="USD", total_minor=1000),
        MonthTotal(month="2026-07", currency="USD", total_minor=1500),
    ]
    delta = month_over_month_delta(current, previous_month="2026-06")
    assert delta == {"USD": 500}


def test_month_over_month_delta_empty_series() -> None:
    assert month_over_month_delta([], previous_month="2026-06") == {}


def test_month_over_month_delta_missing_previous_month_treated_as_zero() -> None:
    current = [MonthTotal(month="2026-07", currency="USD", total_minor=800)]
    delta = month_over_month_delta(current, previous_month="2026-01")
    assert delta == {"USD": 800}
