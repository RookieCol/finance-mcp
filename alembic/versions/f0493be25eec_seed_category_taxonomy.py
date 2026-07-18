"""seed category taxonomy

Revision ID: f0493be25eec
Revises: c1b6c78ff858
Create Date: 2026-07-18 19:10:53.654126

Taxonomy source: finanzas-saas.md (expense categories separate Sales from
Marketing to keep CAC calculable; income kept to a simple set for v1).
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "f0493be25eec"
down_revision: str | Sequence[str] | None = "c1b6c78ff858"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

category_type_enum = sa.Enum("income", "expense", name="category_type", create_type=False)

categories_table = sa.table(
    "categories",
    sa.column("key", sa.String),
    sa.column("type", category_type_enum),
    sa.column("label", sa.String),
)

SEED_ROWS = [
    {"key": "cogs", "type": "expense", "label": "Cost of Goods Sold (hosting, infra, support)"},
    {"key": "sales", "type": "expense", "label": "Sales"},
    {"key": "marketing", "type": "expense", "label": "Marketing"},
    {"key": "rd", "type": "expense", "label": "Research & Development"},
    {"key": "ga", "type": "expense", "label": "General & Administrative"},
    {"key": "subscription", "type": "income", "label": "Subscription revenue"},
    {"key": "services", "type": "income", "label": "Professional services"},
    {"key": "other", "type": "income", "label": "Other income"},
]


def upgrade() -> None:
    op.bulk_insert(categories_table, SEED_ROWS)


def downgrade() -> None:
    keys = [row["key"] for row in SEED_ROWS]
    op.execute(categories_table.delete().where(categories_table.c.key.in_(keys)))
