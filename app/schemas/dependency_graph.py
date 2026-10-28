from datetime import datetime

from pydantic import BaseModel, ConfigDict


class DependencyNode(BaseModel):
    service_name: str
    span_count: int
    error_count: int
    request_count: int
    error_rate_percent: float
    average_duration_ms: float | None

    model_config = ConfigDict(extra="forbid")


class DependencyEdge(BaseModel):
    source: str
    target: str
    request_count: int
    error_count: int
    error_rate_percent: float
    average_duration_ms: float | None
    observed_failure: bool
    last_error_at: datetime | None

    model_config = ConfigDict(extra="forbid")


class FailureRelationship(BaseModel):
    source: str
    target: str
    failed_calls: int
    last_error_at: datetime | None

    model_config = ConfigDict(extra="forbid")


class DependencyGraphResponse(BaseModel):
    trace_id: str | None
    start_time: datetime | None
    end_time: datetime | None
    nodes: list[DependencyNode]
    edges: list[DependencyEdge]
    failure_relationships: list[FailureRelationship]

    model_config = ConfigDict(extra="forbid")


class ServiceDependenciesResponse(BaseModel):
    service: DependencyNode
    incoming: list[DependencyEdge]
    outgoing: list[DependencyEdge]

    model_config = ConfigDict(extra="forbid")
