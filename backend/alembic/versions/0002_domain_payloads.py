"""Store nested domain payloads required to restore a live case."""

import sqlalchemy as sa

from alembic import op

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "risk_events",
        sa.Column("metadata_json", sa.Text(), nullable=False, server_default="{}"),
    )
    op.add_column("recovery_cases", sa.Column("diagnosis_json", sa.Text(), nullable=True))
    op.add_column("recovery_cases", sa.Column("plan_json", sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column("recovery_cases", "plan_json")
    op.drop_column("recovery_cases", "diagnosis_json")
    op.drop_column("risk_events", "metadata_json")
