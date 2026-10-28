import logging

from fastapi import APIRouter, Depends, HTTPException, Path, Query
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.security import require_internal_token, require_role
from app.core.timeutils import utcnow
from app.db.session import get_db
from app.models.alert import Alert
from app.models.alert_rule import AlertRule
from app.schemas.alert import AlertListResponse, AlertResponse, AlertRuleRequest, AlertUpdateRequest
from app.services.alerting import ALERT_TYPES, default_thresholds, evaluate_alerts

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/alerts", tags=["Alerting"], dependencies=[Depends(require_internal_token)])


def serialize_alert(alert: Alert) -> AlertResponse:
    data = AlertResponse.model_validate(alert)
    data.trace_ids = list(alert.trace_ids or [])
    return data


@router.get("", response_model=AlertListResponse, summary="List alerts")
def list_alerts(
    status: str | None = Query(default=None, pattern="^(active|acknowledged|resolved)$"),
    service_name: str | None = Query(default=None, min_length=1, max_length=100),
    alert_type: str | None = Query(default=None, min_length=1, max_length=50),
    severity: str | None = Query(default=None, pattern="^(warning|critical)$"),
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
):
    filters = []
    if status:
        filters.append(Alert.status == status)
    if service_name:
        filters.append(Alert.service_name == service_name)
    if alert_type:
        filters.append(Alert.alert_type == alert_type)
    if severity:
        filters.append(Alert.severity == severity)
    total = db.scalar(select(func.count()).select_from(Alert).where(*filters)) or 0
    alerts = db.scalars(select(Alert).where(*filters).order_by(Alert.last_seen_at.desc(), Alert.id.desc())
                        .limit(limit).offset(offset)).all()
    return AlertListResponse(items=[serialize_alert(a) for a in alerts], total=total, limit=limit, offset=offset)


@router.post("/evaluate", dependencies=[Depends(require_role("admin"))],
             summary="Administrative: aggregate recent metrics and evaluate thresholds now")
def evaluate(db: Session = Depends(get_db)):
    return evaluate_alerts(db)


@router.get("/rules", summary="Effective alert thresholds")
def list_rules(db: Session = Depends(get_db)):
    defaults = default_thresholds()
    overrides = db.scalars(select(AlertRule).order_by(AlertRule.service_name, AlertRule.alert_type)).all()
    return {
        "defaults": [{"alert_type": t, "threshold_value": defaults[t]} for t in ALERT_TYPES],
        "overrides": [{"alert_type": r.alert_type, "service_name": r.service_name,
                       "threshold_value": r.threshold_value, "enabled": r.enabled} for r in overrides],
    }


@router.put("/rules", dependencies=[Depends(require_role("admin"))], summary="Create/update a threshold override")
def upsert_rule(request: AlertRuleRequest, db: Session = Depends(get_db)):
    rule = db.scalar(select(AlertRule).where(AlertRule.alert_type == request.alert_type,
                                             AlertRule.service_name == request.service_name))
    if rule is None:
        rule = AlertRule(alert_type=request.alert_type, service_name=request.service_name,
                         threshold_value=request.threshold_value, enabled=request.enabled)
        db.add(rule)
    else:
        rule.threshold_value, rule.enabled = request.threshold_value, request.enabled
    db.commit()
    return {"alert_type": rule.alert_type, "service_name": rule.service_name,
            "threshold_value": rule.threshold_value, "enabled": rule.enabled}


@router.get("/{alert_id}", response_model=AlertResponse, summary="One alert with its evidence")
def get_alert(alert_id: int = Path(ge=1), db: Session = Depends(get_db)):
    alert = db.get(Alert, alert_id)
    if alert is None:
        raise HTTPException(404, "Alert not found")
    return serialize_alert(alert)


def _transition(db: Session, alert_id: int, target: str) -> AlertResponse:
    alert = db.get(Alert, alert_id)
    if alert is None:
        raise HTTPException(404, "Alert not found")
    if alert.status == target:
        return serialize_alert(alert)
    if alert.status == "resolved":
        raise HTTPException(409, f"A resolved alert cannot be set to '{target}'")
    if target == "acknowledged" and alert.status != "active":
        raise HTTPException(409, f"Cannot acknowledge an alert with status '{alert.status}'")
    alert.status = target
    now = utcnow()
    if target == "acknowledged":
        alert.acknowledged_at = now
    else:
        alert.resolved_at = now
    db.commit()
    db.refresh(alert)
    return serialize_alert(alert)


@router.patch("/{alert_id}", response_model=AlertResponse, dependencies=[Depends(require_role("analyst"))],
              summary="Acknowledge or resolve an alert")
def update_alert(request: AlertUpdateRequest, alert_id: int = Path(ge=1), db: Session = Depends(get_db)):
    return _transition(db, alert_id, request.status)


@router.patch("/{alert_id}/acknowledge", response_model=AlertResponse, dependencies=[Depends(require_role("analyst"))],
              summary="Acknowledge an active alert (kept for compatibility)")
def acknowledge_alert(alert_id: int = Path(ge=1), db: Session = Depends(get_db)):
    return _transition(db, alert_id, "acknowledged")


@router.patch("/{alert_id}/resolve", response_model=AlertResponse, dependencies=[Depends(require_role("analyst"))],
              summary="Resolve an alert (kept for compatibility)")
def resolve_alert(alert_id: int = Path(ge=1), db: Session = Depends(get_db)):
    return _transition(db, alert_id, "resolved")
