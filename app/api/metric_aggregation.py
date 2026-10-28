import logging

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.core.security import require_internal_token, require_role
from app.db.session import get_db
from app.schemas.metric_aggregation import MetricAggregationRequest, MetricAggregationResponse
from app.services.metric_aggregation import aggregate_metrics

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/metrics", tags=["Metrics Aggregation"],
                   dependencies=[Depends(require_internal_token)])


@router.post("/aggregate", response_model=MetricAggregationResponse, dependencies=[Depends(require_role("admin"))],
             summary="Administrative: aggregate one explicit interval")
def run_metric_aggregation(request: MetricAggregationRequest, db: Session = Depends(get_db)):
    try:
        created = aggregate_metrics(db=db, interval_start=request.interval_start, interval_end=request.interval_end)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    return MetricAggregationResponse(message="Metric aggregation completed successfully", aggregates_created=created)
