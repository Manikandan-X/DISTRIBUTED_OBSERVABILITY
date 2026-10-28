
from datetime import datetime

from sqlalchemy import JSON, DateTime, Float, Index, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.db.session import Base
from app.db.types import PreciseDateTime


class TraceSpan(Base):
    __tablename__ = "trace_spans"

    id: Mapped[int] = mapped_column(
        Integer,
        primary_key=True,
        autoincrement=True,
    )

    trace_id: Mapped[str] = mapped_column(
        String(64),
        nullable=False,
    )

    span_id: Mapped[str] = mapped_column(
        String(64),
        nullable=False,
    )

    parent_span_id: Mapped[str | None] = mapped_column(
        String(64),
        nullable=True,
    )

    service_name: Mapped[str] = mapped_column(
        String(100),
        nullable=False,
    )

    operation_name: Mapped[str] = mapped_column(
        String(200),
        nullable=False,
    )

    start_time: Mapped[datetime] = mapped_column(
        PreciseDateTime,
        nullable=False,
    )

    end_time: Mapped[datetime | None] = mapped_column(
        PreciseDateTime,
        nullable=True,
    )

    duration_ms: Mapped[float | None] = mapped_column(
        Float,
        nullable=True,
    )

    status: Mapped[str] = mapped_column(
        String(30),
        nullable=False,
    )

    error_message: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
    )

    correlation_id: Mapped[str | None] = mapped_column(
        String(100),
        nullable=True,
    )

    attributes: Mapped[dict | None] = mapped_column(
        JSON,
        nullable=True,
    )

    __table_args__ = (
        UniqueConstraint(
            "trace_id",
            "span_id",
            name="uq_trace_spans_trace_id_span_id",
        ),
        Index("ix_trace_spans_trace_id", "trace_id"),
        Index("ix_trace_spans_span_id", "span_id"),
        Index("ix_trace_spans_service_name", "service_name"),
        Index("ix_trace_spans_parent_span_id", "parent_span_id"),
        Index("ix_trace_spans_start_time", "start_time"),
    )
