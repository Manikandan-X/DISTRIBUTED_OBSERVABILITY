"""microsecond precision for span/trace timestamps

MySQL DATETIME drops fractions of a second, which made all spans of a request
look simultaneous (trace duration 0, wrong failure ordering).
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import mysql

revision = "traces_0002"
down_revision = "traces_0001"
branch_labels = None
depends_on = None


def _mysql() -> bool:
    return op.get_bind().dialect.name == "mysql"


def upgrade() -> None:
    if not _mysql():
        return
    op.alter_column("traces", "start_time", type_=mysql.DATETIME(fsp=6), existing_nullable=False)
    op.alter_column("traces", "end_time", type_=mysql.DATETIME(fsp=6), existing_nullable=True)
    op.alter_column("trace_spans", "start_time", type_=mysql.DATETIME(fsp=6), existing_nullable=False)
    op.alter_column("trace_spans", "end_time", type_=mysql.DATETIME(fsp=6), existing_nullable=False)


def downgrade() -> None:
    if not _mysql():
        return
    for table, col, null in (("traces", "start_time", False), ("traces", "end_time", True),
                             ("trace_spans", "start_time", False), ("trace_spans", "end_time", False)):
        op.alter_column(table, col, type_=sa.DateTime(), existing_nullable=null)
