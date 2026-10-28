
from datetime import datetime

from sqlalchemy import DateTime, Index, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.session import Base
from app.db.types import PreciseDateTime


class ProcessedLog(Base):
    __tablename__ = "processed_logs"

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

    trace_id: Mapped[str | None] = mapped_column(
        String(64),
        nullable=True,
    )

    span_id: Mapped[str | None] = mapped_column(
        String(64),
        nullable=True,
    )

    correlation_id: Mapped[str | None] = mapped_column(
        String(100),
        nullable=True,
    )

    service_name: Mapped[str] = mapped_column(
        String(100),
        nullable=False,
    )

    severity: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
    )

    message: Mapped[str] = mapped_column(
        Text,
        nullable=False,
    )

    timestamp: Mapped[datetime] = mapped_column(
        PreciseDateTime,
        nullable=False,
    )

    # Groups "the same kind of message" (volatile ids/numbers masked).
    message_fingerprint: Mapped[str] = mapped_column(
        String(40),
        nullable=False,
    )

    # Identity independent of event_id, so the same line is never stored twice.
    dedup_hash: Mapped[str] = mapped_column(
        String(64),
        unique=True,
        nullable=False,
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime,
        nullable=False,
        server_default=func.now(),
    )

    __table_args__ = (
        Index("ix_processed_logs_trace_id", "trace_id"),
        Index("ix_processed_logs_service_name", "service_name"),
        Index("ix_processed_logs_timestamp", "timestamp"),
        Index("ix_processed_logs_correlation_id", "correlation_id"),
        Index("ix_processed_logs_span_id", "span_id"),
        Index("ix_processed_logs_severity", "severity"),
        Index("ix_processed_logs_fingerprint", "message_fingerprint"),
    )
