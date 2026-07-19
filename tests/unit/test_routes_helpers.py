from types import SimpleNamespace

from finance_mcp.core.reporting import CategoryTotal
from finance_mcp.web.routes import (
    _category_breakdown_rows,
    _fmt_money,
    _infer_vendor,
    _infra_breakdown_rows,
)


def test_category_breakdown_rows_sorted_biggest_first_with_labels() -> None:
    totals = [
        CategoryTotal(category="ga", currency="COP", total_minor=330000000),
        CategoryTotal(category="cogs", currency="COP", total_minor=32511120),
    ]
    rows = _category_breakdown_rows(totals)

    assert [r["category"] for r in rows] == ["ga", "cogs"]
    assert rows[0]["label"] == "General & admin"
    assert rows[0]["pct"] + rows[1]["pct"] == 100


def test_category_breakdown_rows_unknown_category_falls_back_to_raw_key() -> None:
    rows = _category_breakdown_rows(
        [CategoryTotal(category="mystery", currency="USD", total_minor=100)]
    )
    assert rows[0]["label"] == "mystery"


def test_infer_vendor_matches_known_keywords_case_insensitively() -> None:
    assert _infer_vendor("VERCEL - standard monthly") == "Vercel"
    assert _infer_vendor("Supabase Pro Plan") == "Supabase"
    assert _infer_vendor("Resend - email API subscription") == "Resend"
    assert _infer_vendor("Registrar Registration Fee - example.com") == "Domain registrar"
    assert _infer_vendor("something else entirely") == "Other infra"


def test_infra_breakdown_rows_groups_and_sorts_by_vendor() -> None:
    transactions = [
        SimpleNamespace(description="Vercel - standard monthly", currency="COP", amount_minor=4000),
        SimpleNamespace(description="Resend subscription", currency="COP", amount_minor=2000),
        SimpleNamespace(description="Registrar fee - a.com", currency="COP", amount_minor=1000),
        SimpleNamespace(description="Registrar fee - b.com", currency="COP", amount_minor=1000),
    ]
    rows = _infra_breakdown_rows(transactions)

    assert rows[0]["label"] == "Vercel"
    by_label = {r["label"]: r for r in rows}
    assert by_label["Domain registrar"]["amount"] == _fmt_money(2000)
    assert sum(r["pct"] for r in rows) == 100
