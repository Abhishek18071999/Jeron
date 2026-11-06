"""financial results balance sheet and year to date

fundamentals-v2 (docs/plans/fundamentals-v2.md): the balance sheet on the quarter's last
day and the year-to-date facts (the cash-flow statement) of each results filing. Existing
rows start empty; `python -m app.cli fundamentals-reparse` fills them from the saved
XBRL files.

Revision ID: 0af7a3654a35
Revises: 17bc3b6809d8
Create Date: 2026-11-01 15:14:39.736171

"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0af7a3654a35"
down_revision: str | Sequence[str] | None = "17bc3b6809d8"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    for name in ("balance", "ytd"):
        op.add_column(
            "financial_results",
            sa.Column(
                name,
                postgresql.JSONB(astext_type=sa.Text()),
                server_default="{}",
                nullable=False,
            ),
        )


def downgrade() -> None:
    op.drop_column("financial_results", "ytd")
    op.drop_column("financial_results", "balance")
