"""microsecond precision for metric sample timestamps"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import mysql

revision = "metrics_0002"
down_revision = "metrics_0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    if op.get_bind().dialect.name == "mysql":
        op.alter_column("metric_samples", "recorded_at", type_=mysql.DATETIME(fsp=6), existing_nullable=False)


def downgrade() -> None:
    if op.get_bind().dialect.name == "mysql":
        op.alter_column("metric_samples", "recorded_at", type_=sa.DateTime(), existing_nullable=False)
