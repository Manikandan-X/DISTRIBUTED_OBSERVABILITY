"""Column types shared by the models."""

from sqlalchemy import DateTime
from sqlalchemy.dialects import mysql

# MySQL DATETIME has whole-second precision by default, which makes every span of
# a request look simultaneous. Analysis columns use microsecond precision.
PreciseDateTime = DateTime().with_variant(mysql.DATETIME(fsp=6), "mysql")
