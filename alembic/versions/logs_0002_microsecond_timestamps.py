"""microsecond precision for log timestamps"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import mysql

revision = "logs_0002"
down_revision = "logs_0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    if op.get_bind().dialect.name == "mysql":
        op.alter_column("processed_logs", "timestamp", type_=mysql.DATETIME(fsp=6), existing_nullable=False)


def downgrade() -> None:
    if op.get_bind().dialect.name == "mysql":
        op.alter_column("processed_logs", "timestamp", type_=sa.DateTime(), existing_nullable=False)
