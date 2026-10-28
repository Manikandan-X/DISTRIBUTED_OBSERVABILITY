
"""Add unique metric aggregate interval constraint."""

from alembic import op


revision = "d1dbd9f4e958"
down_revision = "c31a8e5f72b4"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_unique_constraint(
        "uq_metric_aggregates_service_metric_interval",
        "metric_aggregates",
        [
            "service_name",
            "metric_name",
            "interval_start",
            "interval_end",
        ],
    )


def downgrade() -> None:
    op.drop_constraint(
        "uq_metric_aggregates_service_metric_interval",
        "metric_aggregates",
        type_="unique",
    )
