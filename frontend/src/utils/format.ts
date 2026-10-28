/** The API returns UTC timestamps without a zone suffix; treat them as UTC. */
export function parseUtc(value: string | null | undefined): Date | null {
  if (!value) return null;
  const hasZone = /(Z|[+-]\d{2}:?\d{2})$/.test(value);
  const date = new Date(hasZone ? value : `${value}Z`);
  return Number.isNaN(date.getTime()) ? null : date;
}

export function formatDateTime(value: string | null | undefined): string {
  const d = parseUtc(value);
  return d ? d.toLocaleString(undefined, { hour12: false }) : '–';
}

export function formatTime(value: string | null | undefined): string {
  const d = parseUtc(value);
  return d ? d.toLocaleTimeString(undefined, { hour12: false }) : '–';
}

export function formatMs(value: number | null | undefined): string {
  if (value === null || value === undefined) return '–';
  if (value >= 1000) return `${(value / 1000).toFixed(2)} s`;
  if (value >= 100) return `${value.toFixed(0)} ms`;
  if (value >= 1) return `${value.toFixed(1)} ms`;
  return `${value.toFixed(2)} ms`;
}

export function formatPercent(value: number | null | undefined, digits = 1): string {
  return value === null || value === undefined ? '–' : `${value.toFixed(digits)}%`;
}

export function formatNumber(value: number | null | undefined): string {
  return value === null || value === undefined ? '–' : value.toLocaleString();
}

export function shortId(id: string, length = 8): string {
  return id.length > length ? `${id.slice(0, length)}…` : id;
}

/** ISO string (UTC, no zone) for "N minutes ago", as the API expects. */
export function minutesAgoIso(minutes: number): string {
  return new Date(Date.now() - minutes * 60_000).toISOString().replace('Z', '');
}

export function nowIso(): string {
  return new Date().toISOString().replace('Z', '');
}

/** <input type="datetime-local"> value (local time) -> UTC ISO without zone. */
export function localInputToUtcIso(value: string): string | undefined {
  if (!value) return undefined;
  const d = new Date(value);
  return Number.isNaN(d.getTime()) ? undefined : d.toISOString().replace('Z', '');
}

export const ALERT_TYPE_LABELS: Record<string, string> = {
  error_rate_percent: 'Error rate',
  avg_latency_ms: 'Average latency',
  p95_latency_ms: 'p95 latency',
  request_volume: 'Request volume',
};

export function formatAlertValue(type: string, value: number): string {
  if (type === 'error_rate_percent') return `${value.toFixed(1)}%`;
  if (type === 'request_volume') return `${Math.round(value)} req`;
  return formatMs(value);
}

export const TIME_WINDOWS = [
  { label: 'Last 15 min', minutes: 15 },
  { label: 'Last hour', minutes: 60 },
  { label: 'Last 6 hours', minutes: 360 },
  { label: 'Last 24 hours', minutes: 1440 },
];
