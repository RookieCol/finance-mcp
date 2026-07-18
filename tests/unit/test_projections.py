from finance_mcp.core.projections import (
    forecast_monthly_net,
    growth_rate,
    linear_trend_slope,
    moving_average,
    runway_months,
)


def test_moving_average_hand_computed() -> None:
    # (100 + 200 + 300) / 3 = 200
    assert moving_average([100, 200, 300]) == 200.0


def test_moving_average_empty_series_is_zero() -> None:
    assert moving_average([]) == 0.0


def test_linear_trend_slope_perfectly_flat_series_is_zero() -> None:
    assert linear_trend_slope([100, 100, 100]) == 0.0


def test_linear_trend_slope_hand_computed_increasing_series() -> None:
    # y = 10, 20, 30 at x = 0, 1, 2 -> slope exactly 10
    assert linear_trend_slope([10, 20, 30]) == 10.0


def test_linear_trend_slope_single_point_is_zero() -> None:
    assert linear_trend_slope([42]) == 0.0


def test_forecast_monthly_net_pure_recurring_base_no_history() -> None:
    # No historical non-recurring net, so the forecast is exactly the
    # recurring base every month: 5000 income - 2000 expense = 3000/mo.
    forecast = forecast_monthly_net(
        recurring_income_minor=5000,
        recurring_expense_minor=2000,
        historical_non_recurring_net_minor=[],
        months_ahead=3,
    )
    assert forecast == [3000, 3000, 3000]


def test_forecast_monthly_net_adds_flat_trend_component() -> None:
    # Recurring net = 0. Historical non-recurring net is flat at 500/mo,
    # so the 3-month moving average base is 500 and slope is 0 -> every
    # forecasted month should be exactly 500.
    forecast = forecast_monthly_net(
        recurring_income_minor=0,
        recurring_expense_minor=0,
        historical_non_recurring_net_minor=[500, 500, 500],
        months_ahead=2,
    )
    assert forecast == [500, 500]


def test_runway_months_hand_computed() -> None:
    # 12000 minor units of cash / 2000 minor units burned per month = 6.0
    assert runway_months(12000, 2000) == 6.0


def test_runway_months_is_none_when_not_burning_cash() -> None:
    assert runway_months(12000, 0) is None
    assert runway_months(12000, -500) is None


def test_growth_rate_hand_computed() -> None:
    # (1100 - 1000) / 1000 = 0.10 (+10%)
    assert growth_rate(1100, 1000) == 0.10


def test_growth_rate_is_none_when_previous_period_is_zero() -> None:
    assert growth_rate(1000, 0) is None
