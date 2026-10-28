import logging

from fastapi import APIRouter, Depends, HTTPException, Path, Query
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.security import require_internal_token, require_role
from app.db.session import get_db
from app.models.diagnostic_evidence import DiagnosticEvidence
from app.models.diagnostic_report import DiagnosticReport
from app.schemas.diagnostic import DiagnosticListResponse, DiagnosticReportResponse, EvidenceItem
from app.services.root_cause_analysis import TelemetryUnavailableError, TraceNotFoundError, analyze_trace

logger = logging.getLogger(__name__)

# Diagnostic data is access-controlled: analyst role or higher.
router = APIRouter(prefix="/api/v1/diagnostics", tags=["Root Cause Analysis"],
                   dependencies=[Depends(require_internal_token), Depends(require_role("analyst"))])

TraceId = Path(min_length=1, max_length=64, pattern=r"^[A-Za-z0-9_-]+$")


def _detail(db: Session, report: DiagnosticReport) -> DiagnosticReportResponse:
    items = db.scalars(select(DiagnosticEvidence).where(DiagnosticEvidence.report_id == report.id)
                       .order_by(DiagnosticEvidence.id)).all()
    data = DiagnosticReportResponse.model_validate(report)
    data.evidence_items = [EvidenceItem.model_validate(i) for i in items]
    if isinstance(report.evidence, dict):
        data.warnings = list(report.evidence.get("warnings", []))
    return data


def _analyze(db: Session, trace_id: str) -> DiagnosticReportResponse:
    try:
        return _detail(db, analyze_trace(db=db, trace_id=trace_id))
    except TraceNotFoundError as exc:
        raise HTTPException(404, str(exc)) from exc
    except TelemetryUnavailableError as exc:
        raise HTTPException(503, str(exc)) from exc


@router.post("/analyze/{trace_id}", response_model=DiagnosticReportResponse, status_code=201,
             summary="Analyse a trace with the deterministic diagnostic rules")
def analyze(trace_id: str = TraceId, db: Session = Depends(get_db)):
    return _analyze(db, trace_id)


@router.post("/traces/{trace_id}/analyze", response_model=DiagnosticReportResponse, status_code=201,
             summary="Alias of /analyze/{trace_id} (kept for compatibility)")
def analyze_legacy(trace_id: str = TraceId, db: Session = Depends(get_db)):
    return _analyze(db, trace_id)


@router.get("", response_model=DiagnosticListResponse, summary="List diagnostic reports")
def list_reports(
    trace_id: str | None = Query(default=None, min_length=1, max_length=64, pattern=r"^[A-Za-z0-9_-]+$"),
    affected_service: str | None = Query(default=None, min_length=1, max_length=100),
    severity: str | None = Query(default=None, pattern="^(LOW|MEDIUM|HIGH)$"),
    root_cause_status: str | None = Query(default=None, pattern="^(confirmed|probable|inconclusive|no_issue_detected)$"),
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
):
    filters = []
    if trace_id:
        filters.append(DiagnosticReport.trace_id == trace_id)
    if affected_service:
        filters.append(DiagnosticReport.affected_service == affected_service)
    if severity:
        filters.append(DiagnosticReport.severity == severity)
    if root_cause_status:
        filters.append(DiagnosticReport.root_cause_status == root_cause_status)
    total = db.scalar(select(func.count()).select_from(DiagnosticReport).where(*filters)) or 0
    items = db.scalars(select(DiagnosticReport).where(*filters)
                       .order_by(DiagnosticReport.created_at.desc(), DiagnosticReport.id.desc())
                       .limit(limit).offset(offset)).all()
    return DiagnosticListResponse(items=items, total=total, limit=limit, offset=offset)


@router.get("/{report_id}", response_model=DiagnosticReportResponse, summary="One report with its evidence")
def get_report(report_id: int = Path(ge=1), db: Session = Depends(get_db)):
    report = db.get(DiagnosticReport, report_id)
    if report is None:
        raise HTTPException(404, "Diagnostic report not found")
    return _detail(db, report)
