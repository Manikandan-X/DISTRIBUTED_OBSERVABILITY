
from datetime import datetime

from sqlalchemy import DateTime, Float, Index, Integer, JSON, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.session import Base


class DiagnosticReport(Base):
    __tablename__ = "diagnostic_reports"

    id: Mapped[int] = mapped_column(
        Integer,
        primary_key=True,
        autoincrement=True,
    )

    trace_id: Mapped[str] = mapped_column(
        String(64),
        nullable=False,
    )

    affected_service: Mapped[str] = mapped_column(
        String(100),
        nullable=False,
    )

    severity: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
    )

    diagnosis: Mapped[str] = mapped_column(
        Text,
        nullable=False,
    )

    evidence: Mapped[dict | list | None] = mapped_column(
        JSON,
        nullable=True,
    )

    confidence_level: Mapped[float] = mapped_column(
        Float,
        nullable=False,
    )

    # confirmed | probable | inconclusive | no_issue_detected
    root_cause_status: Mapped[str] = mapped_column(
        String(30),
        nullable=False,
        default="inconclusive",
        server_default="inconclusive",
    )

    rules_version: Mapped[str | None] = mapped_column(
        String(20),
        nullable=True,
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime,
        nullable=False,
        server_default=func.now(),
    )

    __table_args__ = (
        Index("ix_diagnostic_reports_trace_id", "trace_id"),
        Index("ix_diagnostic_reports_affected_service", "affected_service"),
        Index("ix_diagnostic_reports_severity", "severity"),
    )
