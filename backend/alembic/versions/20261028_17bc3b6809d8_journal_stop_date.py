"""journal stop date

The day a journal entry's own stop was last changed, so a split or bonus after it
restates the stop (app/journal/basis.py). Existing rows stay null: read as the first
buy's day, which is what the exit plan assumed before.

Revision ID: 17bc3b6809d8
Revises: f7f3669d9f7d
Create Date: 2026-10-28 21:11:14.040678

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "17bc3b6809d8"
down_revision: str | Sequence[str] | None = "f7f3669d9f7d"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column("journal_entries", sa.Column("stop_set_on", sa.Date(), nullable=True))


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column("journal_entries", "stop_set_on")
