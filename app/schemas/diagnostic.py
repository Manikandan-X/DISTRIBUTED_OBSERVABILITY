from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class EvidenceItem(BaseModel):
    id: int
    evidence_type: str
    reference_id: str
    description: str

    model_config = ConfigDict(from_attributes=True)


class DiagnosticReportSummary(BaseModel):
    id: int
    trace_id: str
    affected_service: str
    severity: str
    diagnosis: str
    confidence_level: float
    root_cause_status: str = "inconclusive"
    rules_version: str | None = None
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class DiagnosticReportResponse(DiagnosticReportSummary):
    evidence: dict | list | None = None
    evidence_items: list[EvidenceItem] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)


class DiagnosticListResponse(BaseModel):
    items: list[DiagnosticReportSummary]
    total: int
    limit: int
    offset: int


__all__ = ["DiagnosticReportResponse", "DiagnosticReportSummary", "DiagnosticListResponse", "EvidenceItem", "Any"]
