
from datetime import datetime

from sqlalchemy import DateTime, Float, Index, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db.session import Base
from app.db.types import PreciseDateTime


class Trace(Base):
    __tablename__ = "traces"

    id: Mapped[int] = mapped_column(
        Integer,
        primary_key=True,
        autoincrement=True,
    )

    trace_id: Mapped[str] = mapped_column(
        String(64),
        unique=True,
        nullable=False,
    )

    root_service: Mapped[str] = mapped_column(
        String(100),
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

    completed_at: Mapped[datetime | None] = mapped_column(
        DateTime,
        nullable=True,
    )

    correlation_id: Mapped[str | None] = mapped_column(
        String(100),
        nullable=True,
    )

    span_count: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=0,
        server_default="0",
    )

    # Spans whose parent_span_id never arrived (set when the trace is finalised).
    missing_span_count: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=0,
        server_default="0",
    )

    # in_progress -> complete | incomplete (see TRACE_COMPLETION_WAIT_SECONDS)
    completion_status: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        default="in_progress",
        server_default="in_progress",
    )

    last_span_received_at: Mapped[datetime | None] = mapped_column(
        DateTime,
        nullable=True,
    )

    __table_args__ = (
        Index("ix_traces_root_service", "root_service"),
        Index("ix_traces_correlation_id", "correlation_id"),
        Index("ix_traces_completion_status", "completion_status"),
        Index("ix_traces_status", "status"),
        Index("ix_traces_start_time", "start_time"),
    )
