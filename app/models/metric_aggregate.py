
from datetime import datetime

from sqlalchemy import DateTime, Float, Index, Integer, JSON, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.db.session import Base


class MetricAggregate(Base):
    __tablename__ = "metric_aggregates"

    id: Mapped[int] = mapped_column(
        Integer,
        primary_key=True,
        autoincrement=True,
    )

    service_name: Mapped[str] = mapped_column(
        String(100),
        nullable=False,
    )

    metric_name: Mapped[str] = mapped_column(
        String(150),
        nullable=False,
    )

    interval_start: Mapped[datetime] = mapped_column(
        DateTime,
        nullable=False,
    )

    interval_end: Mapped[datetime] = mapped_column(
        DateTime,
        nullable=False,
    )

    sample_count: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
    )

    average_value: Mapped[float] = mapped_column(
        Float,
        nullable=False,
    )

    minimum_value: Mapped[float] = mapped_column(
        Float,
        nullable=False,
    )

    maximum_value: Mapped[float] = mapped_column(
        Float,
        nullable=False,
    )

    percentile_data: Mapped[dict | None] = mapped_column(
        JSON,
        nullable=True,
    )

    __table_args__ = (
        UniqueConstraint(
            "service_name",
            "metric_name",
            "interval_start",
            "interval_end",
            name="uq_metric_aggregates_service_metric_interval",
        ),
        Index("ix_metric_aggregates_service_name", "service_name"),
        Index("ix_metric_aggregates_metric_name", "metric_name"),
        Index("ix_metric_aggregates_interval_start", "interval_start"),
    )
