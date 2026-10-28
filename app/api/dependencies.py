from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Path, Query
from sqlalchemy.orm import Session

from app.core.security import require_internal_token
from app.db.session import get_db
from app.schemas.dependency_graph import DependencyGraphResponse, ServiceDependenciesResponse
from app.services.dependency_graph import build_dependency_graph, service_dependencies

router = APIRouter(prefix="/api/v1/dependencies", tags=["Service Dependencies"],
                   dependencies=[Depends(require_internal_token)])


def _check_range(start_time, end_time):
    if start_time is not None and end_time is not None and end_time <= start_time:
        raise HTTPException(400, "end_time must be later than start_time")


@router.get("", response_model=DependencyGraphResponse, summary="Service dependency graph from observed spans")
def get_dependencies(
    trace_id: str | None = Query(default=None, min_length=1, max_length=64, pattern=r"^[A-Za-z0-9_-]+$"),
    start_time: datetime | None = Query(default=None),
    end_time: datetime | None = Query(default=None),
    db: Session = Depends(get_db),
):
    _check_range(start_time, end_time)
    return build_dependency_graph(db, trace_id=trace_id, start_time=start_time, end_time=end_time)


@router.get("/{service_name}", response_model=ServiceDependenciesResponse,
            summary="Incoming and outgoing dependencies of one service")
def get_service_dependencies(
    service_name: str = Path(min_length=1, max_length=100),
    start_time: datetime | None = Query(default=None),
    end_time: datetime | None = Query(default=None),
    db: Session = Depends(get_db),
):
    _check_range(start_time, end_time)
    result = service_dependencies(db, service_name, start_time=start_time, end_time=end_time)
    if result is None:
        raise HTTPException(404, f"Service not found in observed telemetry: {service_name}")
    return result
