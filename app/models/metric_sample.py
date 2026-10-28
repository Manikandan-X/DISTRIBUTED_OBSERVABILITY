
from datetime import datetime

from sqlalchemy import DateTime, Float, Index, Integer, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.session import Base
from app.db.types import PreciseDateTime


class MetricSample(Base):
    __tablename__ = "metric_samples"

    id: Mapped[int] = mapped_column(
        Integer,
        primary_key=True,
        autoincrement=True,
    )

    event_id: Mapped[str] = mapped_column(
        String(100),
        unique=True,
        nullable=False,
    )

    service_name: Mapped[str] = mapped_column(
        String(100),
        nullable=False,
    )

    metric_name: Mapped[str] = mapped_column(
        String(150),
        nullable=False,
    )

    metric_value: Mapped[float] = mapped_column(
        Float,
        nullable=False,
    )

    # Optional link back to the request that produced the sample; lets alerts
    # reference concrete traces.
    trace_id: Mapped[str | None] = mapped_column(
        String(64),
        nullable=True,
    )

    recorded_at: Mapped[datetime] = mapped_column(
        PreciseDateTime,
        nullable=False,
    )

    __table_args__ = (
        Index("ix_metric_samples_service_name", "service_name"),
        Index("ix_metric_samples_metric_name", "metric_name"),
        Index("ix_metric_samples_recorded_at", "recorded_at"),
        Index("ix_metric_samples_service_metric_time", "service_name", "metric_name", "recorded_at"),
    )
