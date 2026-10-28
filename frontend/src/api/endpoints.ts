import { http } from './client';
import type {
  Alert,
  AlertRules,
  AlertStatus,
  DependencyGraph,
  DiagnosticDetail,
  DiagnosticSummary,
  LogPattern,
  LogRecord,
  OverviewSummary,
  Page,
  SeriesMetric,
  ServiceDependencies,
  ServiceHealthItem,
  ServicesMetricsResponse,
  TimeSeries,
  TokenResponse,
  TraceDetail,
  TraceListItem,
} from './types';

type Params = Record<string, string | number | boolean | undefined | null>;

/** Drop empty values so the backend never sees "x=" for an unset filter. */
const clean = (params: Params = {}) =>
  Object.fromEntries(Object.entries(params).filter(([, v]) => v !== undefined && v !== null && v !== ''));

const get = async <T>(url: string, params?: Params): Promise<T> =>
  (await http.get<T>(url, { params: clean(params) })).data;

export const api = {
  // auth
  login: async (username: string, password: string) =>
    (await http.post<TokenResponse>('/auth/login', { username, password })).data,
  me: () => get<{ username: string; role: string }>('/auth/me'),

  // overview
  overview: (minutes: number) => get<OverviewSummary>('/overview', { minutes }),
  servicesHealth: (minutes: number) =>
    get<{ items: ServiceHealthItem[]; total: number }>('/services/health', { minutes }),

  // traces
  traces: (params: Params) => get<Page<TraceListItem>>('/traces', params),
  trace: (traceId: string) => get<TraceDetail>(`/traces/${encodeURIComponent(traceId)}`),

  // logs
  logs: (params: Params) => get<Page<LogRecord>>('/logs', params),
  logPatterns: (params: Params) => get<{ items: LogPattern[]; total: number }>('/logs/patterns', params),

  // metrics
  metricsServices: (minutes: number) => get<ServicesMetricsResponse>('/metrics/services', { minutes }),
  timeseries: (metric: SeriesMetric, serviceName: string | undefined, startTime: string, endTime: string) =>
    get<TimeSeries>('/metrics/timeseries', { metric, service_name: serviceName, start_time: startTime, end_time: endTime }),

  // dependencies
  dependencies: (startTime?: string) => get<DependencyGraph>('/dependencies', { start_time: startTime }),
  serviceDependencies: (service: string, startTime?: string) =>
    get<ServiceDependencies>(`/dependencies/${encodeURIComponent(service)}`, { start_time: startTime }),

  // diagnostics
  diagnostics: (params: Params) => get<Page<DiagnosticSummary>>('/diagnostics', params),
  diagnostic: (id: number) => get<DiagnosticDetail>(`/diagnostics/${id}`),
  analyze: async (traceId: string) =>
    (await http.post<DiagnosticDetail>(`/diagnostics/analyze/${encodeURIComponent(traceId)}`)).data,

  // alerts
  alerts: (params: Params) => get<Page<Alert>>('/alerts', params),
  updateAlert: async (id: number, status: Exclude<AlertStatus, 'active'>) =>
    (await http.patch<Alert>(`/alerts/${id}`, { status })).data,
  alertRules: () => get<AlertRules>('/alerts/rules'),
  saveAlertRule: async (rule: { alert_type: string; service_name: string; threshold_value: number; enabled: boolean }) =>
    (await http.put('/alerts/rules', rule)).data,
};
