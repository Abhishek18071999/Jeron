"""M1 data: source files, series per bar, one instrument per symbol

Revision ID: 7b1f2c9d4e10
Revises: e3d629689957
Create Date: 2026-09-30 19:00:00

"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "7b1f2c9d4e10"
down_revision: str | Sequence[str] | None = "e3d629689957"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "source_files",
        sa.Column("source", sa.String(length=32), nullable=False),
        sa.Column("trade_date", sa.Date(), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("url", sa.String(length=300), nullable=True),
        sa.Column("sha256", sa.String(length=64), nullable=True),
        sa.Column("rows", sa.Integer(), nullable=True),
        sa.Column("details", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column(
            "fetched_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("source", "trade_date"),
    )

    op.drop_constraint("instruments_exchange_symbol_series_key", "instruments", type_="unique")
    op.create_unique_constraint(
        "instruments_exchange_symbol_key", "instruments", ["exchange", "symbol"]
    )

    op.add_column("daily_bars", sa.Column("series", sa.String(length=4), nullable=True))

    op.add_column(
        "corporate_actions",
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
    )
    op.create_unique_constraint(
        "uq_corporate_actions_identity",
        "corporate_actions",
        ["instrument_id", "source", "ex_date", "action_type", "raw_text"],
        postgresql_nulls_not_distinct=True,
    )

    op.drop_index("ix_data_quality_reports_trade_date", table_name="data_quality_reports")
    op.create_index(
        "ix_data_quality_reports_trade_date",
        "data_quality_reports",
        ["trade_date"],
        unique=True,
    )


def downgrade() -> None:
    op.drop_index("ix_data_quality_reports_trade_date", table_name="data_quality_reports")
    op.create_index(
        "ix_data_quality_reports_trade_date",
        "data_quality_reports",
        ["trade_date"],
        unique=False,
    )
    op.drop_constraint("uq_corporate_actions_identity", "corporate_actions", type_="unique")
    op.drop_column("corporate_actions", "created_at")
    op.drop_column("daily_bars", "series")
    op.drop_constraint("instruments_exchange_symbol_key", "instruments", type_="unique")
    op.create_unique_constraint(
        "instruments_exchange_symbol_series_key",
        "instruments",
        ["exchange", "symbol", "series"],
    )
    op.drop_table("source_files")
