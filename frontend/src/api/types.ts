// Types mirror the backend responses (see the backend README, section 7).

export type Role = 'viewer' | 'analyst' | 'admin';

export interface Page<T> {
  items: T[];
  total: number;
  limit: number;
  offset: number;
}

export interface ApiErrorBody {
  error: {
    code: string;
    message: string;
    source: string;
    correlation_id?: string | null;
    details?: { field: string; message: string }[];
  };
}

export interface TokenResponse {
  access_token: string;
  token_type: string;
  expires_in: number;
  role: Role;
}

// ---------------------------------------------------------------- overview
export interface OverviewSummary {
  total_requests: number;
  error_rate_percent: number;
  average_latency_ms: number | null;
  p95_latency_ms: number | null;
  p99_latency_ms: number | null;
  services_reporting_errors: number;
  active_alerts: number;
  window_minutes: number | null;
  partial: boolean;
  warnings: string[];
}

export interface ServiceHealthItem {
  service_name: string;
  request_count: number;
  error_count: number;
  error_rate_percent: number;
  average_latency_ms: number | null;
  p95_latency_ms: number | null;
}

// ------------------------------------------------------------------ traces
export interface TraceListItem {
  id: number;
  trace_id: string;
  root_service: string;
  start_time: string;
  end_time: string | null;
  duration_ms: number | null;
  status: string;
  completed_at: string | null;
  correlation_id: string | null;
  span_count: number;
  missing_span_count: number;
  completion_status: 'in_progress' | 'complete' | 'incomplete';
}

export interface Span {
  span_id: string;
  parent_span_id: string | null;
  service_name: string;
  operation_name: string;
  start_time: string;
  end_time: string | null;
  duration_ms: number | null;
  status: string;
  error_message: string | null;
  correlation_id: string | null;
  attributes: Record<string, string | number | boolean | null> | null;
  depth: number;
  is_failed: boolean;
  is_slow: boolean;
  is_orphan: boolean;
}

export interface ServiceLatency {
  service_name: string;
  self_time_ms: number;
  span_count: number;
  share: number;
}

export type Severity = 'INFO' | 'WARNING' | 'ERROR' | 'CRITICAL';

export interface LogRecord {
  id: number;
  event_id: string;
  trace_id: string | null;
  span_id: string | null;
  correlation_id: string | null;
  service_name: string;
  severity: Severity;
  message: string;
  timestamp: string;
  created_at: string;
}

export interface TraceDetail {
  trace: TraceListItem;
  spans: Span[];
  request_path: string[];
  service_latency: ServiceLatency[];
  failed_span_ids: string[];
  slow_span_ids: string[];
  missing_parent_span_ids: string[];
  is_complete: boolean;
  logs: LogRecord[];
  diagnostic_reports: DiagnosticSummary[];
  partial: boolean;
  warnings: string[];
}

// -------------------------------------------------------------------- logs
export interface LogPattern {
  service_name: string;
  severity: Severity;
  fingerprint: string;
  sample_message: string;
  occurrence_count: number;
  first_seen: string;
  last_seen: string;
  example_trace_ids: string[];
}

// ----------------------------------------------------------------- metrics
export interface ServiceMetrics {
  service_name: string;
  request_count: number;
  error_count: number;
  error_rate_percent: number;
  average_latency_ms: number | null;
  p50_latency_ms: number | null;
  p90_latency_ms: number | null;
  p95_latency_ms: number | null;
  p99_latency_ms: number | null;
  throughput_per_second: number;
}

export interface ServicesMetricsResponse {
  window_minutes: number;
  percentile_method: string;
  items: ServiceMetrics[];
  total: number;
}

export type SeriesMetric =
  | 'request_count'
  | 'error_rate'
  | 'avg_latency'
  | 'p95_latency'
  | 'p99_latency'
  | 'throughput';

export interface SeriesPoint {
  bucket_start: string;
  value: number | null;
  missing: boolean;
}

export interface TimeSeries {
  metric: SeriesMetric;
  service_name: string | null;
  bucket_seconds: number;
  start_time: string;
  end_time: string;
  points: SeriesPoint[];
  missing_buckets: number;
}

// ------------------------------------------------------------ dependencies
export interface DependencyNodeData {
  service_name: string;
  span_count: number;
  error_count: number;
  request_count: number;
  error_rate_percent: number;
  average_duration_ms: number | null;
}

export interface DependencyEdgeData {
  source: string;
  target: string;
  request_count: number;
  error_count: number;
  error_rate_percent: number;
  average_duration_ms: number | null;
  observed_failure: boolean;
  last_error_at: string | null;
}

export interface DependencyGraph {
  nodes: DependencyNodeData[];
  edges: DependencyEdgeData[];
  failure_relationships: { source: string; target: string; failed_calls: number; last_error_at: string | null }[];
}

export interface ServiceDependencies {
  service: DependencyNodeData;
  incoming: DependencyEdgeData[];
  outgoing: DependencyEdgeData[];
}

// ------------------------------------------------------------- diagnostics
export type RootCauseStatus = 'confirmed' | 'probable' | 'inconclusive' | 'no_issue_detected';

export interface DiagnosticSummary {
  id: number;
  trace_id: string;
  affected_service: string;
  severity: 'LOW' | 'MEDIUM' | 'HIGH';
  diagnosis: string;
  confidence_level: number;
  root_cause_status: RootCauseStatus;
  rules_version: string | null;
  created_at: string;
}

export interface EvidenceItem {
  id: number;
  evidence_type: 'trace_span' | 'log' | 'metric' | 'alert' | 'latency' | string;
  reference_id: string;
  description: string;
}

export interface RankedService {
  service_name: string;
  classification: 'confirmed' | 'potential' | 'symptom';
  score: number;
  reasons: string[];
  span_ids: string[];
}

export interface DiagnosticEvidence {
  trace_id: string;
  root_cause_status: RootCauseStatus;
  first_failing_span_id: string | null;
  request_path: string[];
  failure_timeline: { timestamp: string; service_name: string; span_id: string; event: string }[];
  latency_contribution: ServiceLatency[];
  ranked_services: RankedService[];
  limitations: string[];
  warnings: string[];
  span_count: number;
  failed_span_count: number;
  error_log_count: number;
  related_trace_ids: string[];
}

export interface DiagnosticDetail extends DiagnosticSummary {
  evidence: DiagnosticEvidence | null;
  evidence_items: EvidenceItem[];
  warnings: string[];
}

// ------------------------------------------------------------------ alerts
export type AlertStatus = 'active' | 'acknowledged' | 'resolved';

export interface Alert {
  id: number;
  service_name: string;
  alert_type: 'error_rate_percent' | 'avg_latency_ms' | 'p95_latency_ms' | 'request_volume' | string;
  severity: 'warning' | 'critical';
  measured_value: number;
  threshold_value: number;
  status: AlertStatus;
  first_seen_at: string;
  last_seen_at: string;
  occurrence_count: number;
  trace_ids: string[];
  acknowledged_at: string | null;
  resolved_at: string | null;
}

export interface AlertRules {
  defaults: { alert_type: string; threshold_value: number }[];
  overrides: { alert_type: string; service_name: string; threshold_value: number; enabled: boolean }[];
}
