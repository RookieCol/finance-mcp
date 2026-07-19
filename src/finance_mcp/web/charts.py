"""Server-side SVG chart rendering — no JS charting library, no build
step. Each function returns a ``Markup`` string ready to drop straight
into a Jinja template with ``{{ chart }}`` (already marked safe so the
SVG isn't escaped). Colors are always CSS custom properties (``var(--pos)``
etc.) so a chart drawn once survives both light and dark mode.
"""

from dataclasses import dataclass
from datetime import date
from html import escape

from markupsafe import Markup

from finance_mcp.core import reporting


@dataclass(frozen=True)
class BarPoint:
    label: str
    value_minor: int
    is_forecast: bool = False


def build_net_series(
    history: list[reporting.MonthTotal],
    forecast_minor: list[int],
    today: date,
    *,
    max_history_months: int = 6,
) -> list[BarPoint]:
    """Merge historical monthly net totals with a forward-looking
    forecast into one ordered series, trimmed to the trailing
    ``max_history_months``. Ported from the old flexbox-bar helper so
    the dashboard and /projections page can share one series builder.
    """
    months = sorted({m.month for m in history})[-max_history_months:]
    history_by_month: dict[str, int] = {}
    for m in history:
        history_by_month[m.month] = history_by_month.get(m.month, 0) + m.total_minor

    points = [BarPoint(label=m, value_minor=history_by_month.get(m, 0)) for m in months]

    forecast_start = today.replace(day=1)
    for i, amount in enumerate(forecast_minor):
        forecast_month = add_months(forecast_start, i + 1)
        points.append(
            BarPoint(label=forecast_month.strftime("%Y-%m"), value_minor=amount, is_forecast=True)
        )
    return points


def add_months(d: date, months: int) -> date:
    month_index = d.month - 1 + months
    year = d.year + month_index // 12
    month = month_index % 12 + 1
    return date(year, month, 1)


def monthly_net_bar_svg(points: list[BarPoint], *, height: int = 160) -> Markup:
    """Vertical bar chart with a zero baseline — forecast bars are drawn
    with reduced opacity and a dashed outline via the ``forecast`` CSS
    class.
    """
    if not points:
        return Markup("")

    width = max(len(points) * 64, 240)
    label_h = 16
    plot_h = height - label_h
    baseline = plot_h / 2
    max_abs = max(abs(p.value_minor) for p in points) or 1
    bar_w = (width / len(points)) * 0.5

    parts = [
        f'<svg class="chart-svg" viewBox="0 0 {width} {height}" '
        f'preserveAspectRatio="xMidYMid meet" role="img" aria-label="Monthly net cash flow chart">'
    ]
    parts.append(f'<line class="chart-axis" x1="0" y1="{baseline}" x2="{width}" y2="{baseline}"/>')

    slot_w = width / len(points)
    for i, p in enumerate(points):
        cx = slot_w * i + slot_w / 2
        # Cap bar height at baseline - 20 so the value label above a
        # full-height positive bar and below a full-height negative bar
        # both stay inside the plot area instead of colliding with the
        # month labels along the bottom edge.
        bar_h = (abs(p.value_minor) / max_abs) * (baseline - 20)
        tone = "pos" if p.value_minor >= 0 else "neg"
        classes = f"chart-bar {tone}" + (" forecast" if p.is_forecast else "")
        y = baseline - bar_h if p.value_minor >= 0 else baseline
        parts.append(
            f'<rect class="{classes}" x="{cx - bar_w / 2:.1f}" y="{y:.1f}" '
            f'width="{bar_w:.1f}" height="{max(bar_h, 1):.1f}" rx="3"/>'
        )
        display = f"{p.value_minor / 100:,.0f}"
        value_y = (y - 5) if p.value_minor >= 0 else (y + bar_h + 12)
        value_text = escape(display)
        parts.append(
            f'<text class="chart-value" x="{cx:.1f}" y="{value_y:.1f}" '
            f'text-anchor="middle">{value_text}</text>'
        )
        label = p.label[-2:] if len(p.label) == 7 else p.label
        parts.append(
            f'<text class="chart-label" x="{cx:.1f}" y="{height - 3}" text-anchor="middle">'
            f'{escape(label)}{" *" if p.is_forecast else ""}</text>'
        )

    parts.append("</svg>")
    return Markup("".join(parts))


def sparkline_svg(values: list[int], *, width: int = 200, height: int = 48) -> Markup:
    """A single-path trend line over ``values`` (e.g. monthly net,
    oldest first) with a soft fill beneath it.
    """
    if not values:
        return Markup("")
    if len(values) == 1:
        values = [values[0], values[0]]

    lo, hi = min(values), max(values)
    span = (hi - lo) or 1
    pad = 4
    step = (width - pad * 2) / (len(values) - 1)

    def coords(i: int, v: int) -> tuple[float, float]:
        x = pad + step * i
        y = height - pad - ((v - lo) / span) * (height - pad * 2)
        return x, y

    pts = [coords(i, v) for i, v in enumerate(values)]
    path_d = "M" + " L".join(f"{x:.1f} {y:.1f}" for x, y in pts)
    fill_d = path_d + f" L{pts[-1][0]:.1f} {height} L{pts[0][0]:.1f} {height} Z"

    svg = (
        f'<svg class="chart-svg" viewBox="0 0 {width} {height}" '
        f'preserveAspectRatio="xMidYMid meet" role="img" aria-label="Trend sparkline">'
        f'<path class="chart-spark-fill" d="{fill_d}"/>'
        f'<path class="chart-spark" d="{path_d}"/>'
        "</svg>"
    )
    return Markup(svg)
