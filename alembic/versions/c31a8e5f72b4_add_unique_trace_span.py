
"""Add unique constraint for trace and span IDs."""

from alembic import op


revision = "c31a8e5f72b4"
down_revision = "192f7259940a"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_unique_constraint(
        "uq_trace_spans_trace_id_span_id",
        "trace_spans",
        ["trace_id", "span_id"],
    )


def downgrade() -> None:
    op.drop_constraint(
        "uq_trace_spans_trace_id_span_id",
        "trace_spans",
        type_="unique",
    )
