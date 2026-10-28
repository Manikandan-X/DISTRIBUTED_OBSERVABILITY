import { Box, Card, CardContent, FormControlLabel, MenuItem, Stack, Switch, Table, TableBody, TableCell, TableHead, TableRow, TextField, Typography } from '@mui/material';
import Grid from '@mui/material/Grid2';
import { useMemo, useState } from 'react';
import { Area, AreaChart, Bar, BarChart, CartesianGrid, Legend, Line, LineChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts';
import { api } from '../api/endpoints';
import type { TimeSeries } from '../api/types';
import { EmptyState, ErrorAlert, LoadingBar } from '../components/AsyncState';
import { PageHeader, TimeWindowSelect } from '../components/Common';
import { useAsync } from '../hooks/useAsync';
import { serviceColor } from '../theme';
import { formatMs, formatNumber, formatPercent, formatTime, minutesAgoIso, nowIso, parseUtc } from '../utils/format';

interface Point {
  t: number;
  [key: string]: number | null;
}

/** Merge several series into rows keyed by bucket time; gaps stay null. */
function merge(series: Record<string, TimeSeries | undefined>): Point[] {
  const rows = new Map<number, Point>();
  for (const [key, s] of Object.entries(series)) {
    s?.points.forEach((p) => {
      const t = parseUtc(p.bucket_start)?.getTime();
      if (t === undefined) return;
      const row = rows.get(t) ?? { t };
      row[key] = p.missing ? null : p.value;
      rows.set(t, row);
    });
  }
  return [...rows.values()].sort((a, b) => a.t - b.t);
}

const tick = (t: number) => new Date(t).toLocaleTimeString(undefined, { hour: '2-digit', minute: '2-digit', hour12: false });
const NO_ANIMATION = { isAnimationActive: false } as const;

export default function MetricsPage() {
  const [minutes, setMinutes] = useState(60);
  const [service, setService] = useState('');
  const [auto, setAuto] = useState(true);
  const poll = auto ? 15000 : 0;

  const services = useAsync(() => api.metricsServices(minutes), [minutes], poll);

  const series = useAsync(
    async () => {
      const start = minutesAgoIso(minutes);
      const end = nowIso();
      const svc = service || undefined;
      const [requests, errors, avg, p95] = await Promise.all([
        api.timeseries('request_count', svc, start, end),
        api.timeseries('error_rate', svc, start, end),
        api.timeseries('avg_latency', svc, start, end),
        svc ? api.timeseries('p95_latency', svc, start, end) : Promise.resolve(undefined),
      ]);
      return { requests, errors, avg, p95 };
    },
    [minutes, service],
    poll,
  );

  const s = series.data;
  const requestRows = useMemo(() => merge({ requests: s?.requests }), [s]);
  const errorRows = useMemo(() => merge({ error_rate: s?.errors }), [s]);
  const latencyRows = useMemo(() => merge({ avg: s?.avg, p95: s?.p95 }), [s]);
  const missing = s?.requests.missing_buckets ?? 0;
  const total = s?.requests.points.length ?? 0;
  const hasData = !!s && s.requests.points.some((p) => !p.missing);

  return (
    <>
      <PageHeader
        title="Metrics"
        subtitle="Time-bucketed request volume, error rate and latency"
        actions={
          <>
            <FormControlLabel control={<Switch checked={auto} onChange={(e) => setAuto(e.target.checked)} />} label="Auto-refresh" />
            <TextField select size="small" label="Service" value={service} onChange={(e) => setService(e.target.value)} sx={{ minWidth: 200 }}>
              <MenuItem value="">All services</MenuItem>
              {services.data?.items.map((i) => (
                <MenuItem key={i.service_name} value={i.service_name}>
                  {i.service_name}
                </MenuItem>
              ))}
            </TextField>
            <TimeWindowSelect value={minutes} onChange={setMinutes} />
          </>
        }
      />
      <LoadingBar loading={(series.loading && !s) || (services.loading && !services.data)} />
      {series.error && <ErrorAlert error={series.error} onRetry={series.reload} />}

      {s && !hasData && <EmptyState>No metric samples were aggregated in this window yet. Metrics are aggregated every 30 s.</EmptyState>}

      {s && hasData && (
        <>
          <Typography variant="caption" color="text.secondary" sx={{ display: 'block', mb: 1 }}>
            {missing > 0 ? `${missing} of ${total} one-minute buckets had no data and are shown as gaps.` : 'All one-minute buckets contain data.'}
          </Typography>
          <Grid container spacing={2} sx={{ mb: 2 }}>
            <Grid size={{ xs: 12, lg: 6 }}>
              <ChartCard title="Request volume" subtitle="requests per minute">
                <AreaChart data={requestRows}>
                  <CartesianGrid strokeDasharray="3 3" />
                  <XAxis dataKey="t" type="number" domain={['dataMin', 'dataMax']} tickFormatter={tick} />
                  <YAxis allowDecimals={false} />
                  <Tooltip labelFormatter={(t: number) => formatTime(new Date(t).toISOString())} />
                  <Area type="monotone" dataKey="requests" name="Requests" stroke="#1f4fd8" fill="#1f4fd855" connectNulls={false} {...NO_ANIMATION} />
                </AreaChart>
              </ChartCard>
            </Grid>
            <Grid size={{ xs: 12, lg: 6 }}>
              <ChartCard title="Error rate" subtitle="% of failed requests per minute">
                <LineChart data={errorRows}>
                  <CartesianGrid strokeDasharray="3 3" />
                  <XAxis dataKey="t" type="number" domain={['dataMin', 'dataMax']} tickFormatter={tick} />
                  <YAxis unit="%" domain={[0, 'auto']} />
                  <Tooltip labelFormatter={(t: number) => formatTime(new Date(t).toISOString())} formatter={(v: number) => formatPercent(v)} />
                  <Line type="monotone" dataKey="error_rate" name="Error rate" stroke="#d32f2f" dot={false} strokeWidth={2} connectNulls={false} {...NO_ANIMATION} />
                </LineChart>
              </ChartCard>
            </Grid>
            <Grid size={{ xs: 12 }}>
              <ChartCard title="Latency trend" subtitle={service ? 'average and p95 (nearest-rank) per minute' : 'average per minute; select a service to add p95'}>
                <LineChart data={latencyRows}>
                  <CartesianGrid strokeDasharray="3 3" />
                  <XAxis dataKey="t" type="number" domain={['dataMin', 'dataMax']} tickFormatter={tick} />
                  <YAxis tickFormatter={(v: number) => formatMs(v)} width={70} />
                  <Tooltip labelFormatter={(t: number) => formatTime(new Date(t).toISOString())} formatter={(v: number) => formatMs(v)} />
                  <Legend />
                  <Line type="monotone" dataKey="avg" name="Average" stroke="#1f4fd8" dot={false} strokeWidth={2} connectNulls={false} {...NO_ANIMATION} />
                  {service && <Line type="monotone" dataKey="p95" name="p95" stroke="#ed8b00" dot={false} strokeWidth={2} connectNulls={false} {...NO_ANIMATION} />}
                </LineChart>
              </ChartCard>
            </Grid>
          </Grid>
        </>
      )}

      <Typography variant="h6" sx={{ mb: 1 }}>
        Service comparison
      </Typography>
      {services.error && <ErrorAlert error={services.error} onRetry={services.reload} />}
      {services.data && services.data.items.length === 0 && <EmptyState>No metric samples in this window.</EmptyState>}
      {!!services.data?.items.length && (
        <>
          <Grid container spacing={2} sx={{ mb: 2 }}>
            <Grid size={{ xs: 12, md: 4 }}>
              <ChartCard title="Requests" height={240}>
                <BarChart data={services.data.items} layout="vertical" margin={{ left: 30 }}>
                  <CartesianGrid strokeDasharray="3 3" horizontal={false} />
                  <XAxis type="number" allowDecimals={false} />
                  <YAxis type="category" dataKey="service_name" width={130} />
                  <Tooltip />
                  <Bar dataKey="request_count" name="Requests" fill="#1f4fd8" radius={[0, 4, 4, 0]} {...NO_ANIMATION} />
                </BarChart>
              </ChartCard>
            </Grid>
            <Grid size={{ xs: 12, md: 4 }}>
              <ChartCard title="Error rate (%)" height={240}>
                <BarChart data={services.data.items} layout="vertical" margin={{ left: 30 }}>
                  <CartesianGrid strokeDasharray="3 3" horizontal={false} />
                  <XAxis type="number" domain={[0, 'auto']} />
                  <YAxis type="category" dataKey="service_name" width={130} />
                  <Tooltip formatter={(v: number) => formatPercent(v)} />
                  <Bar dataKey="error_rate_percent" name="Error rate" fill="#d32f2f" radius={[0, 4, 4, 0]} {...NO_ANIMATION} />
                </BarChart>
              </ChartCard>
            </Grid>
            <Grid size={{ xs: 12, md: 4 }}>
              <ChartCard title="p95 latency" height={240}>
                <BarChart data={services.data.items} layout="vertical" margin={{ left: 30 }}>
                  <CartesianGrid strokeDasharray="3 3" horizontal={false} />
                  <XAxis type="number" tickFormatter={(v: number) => formatMs(v)} />
                  <YAxis type="category" dataKey="service_name" width={130} />
                  <Tooltip formatter={(v: number) => formatMs(v)} />
                  <Bar dataKey="p95_latency_ms" name="p95" fill="#ed8b00" radius={[0, 4, 4, 0]} {...NO_ANIMATION} />
                </BarChart>
              </ChartCard>
            </Grid>
          </Grid>

          <Card>
            <Box sx={{ overflowX: 'auto' }}>
              <Table size="small">
                <TableHead>
                  <TableRow>
                    <TableCell>Service</TableCell>
                    <TableCell align="right">Requests</TableCell>
                    <TableCell align="right">Errors</TableCell>
                    <TableCell align="right">Error rate</TableCell>
                    <TableCell align="right">Throughput</TableCell>
                    <TableCell align="right">Avg</TableCell>
                    <TableCell align="right">p50</TableCell>
                    <TableCell align="right">p90</TableCell>
                    <TableCell align="right">p95</TableCell>
                    <TableCell align="right">p99</TableCell>
                  </TableRow>
                </TableHead>
                <TableBody>
                  {services.data.items.map((i) => (
                    <TableRow key={i.service_name} hover>
                      <TableCell sx={{ fontWeight: 600, color: serviceColor(i.service_name) }}>{i.service_name}</TableCell>
                      <TableCell align="right">{formatNumber(i.request_count)}</TableCell>
                      <TableCell align="right">{formatNumber(i.error_count)}</TableCell>
                      <TableCell align="right" sx={{ color: i.error_rate_percent >= 20 ? 'error.main' : undefined }}>{formatPercent(i.error_rate_percent)}</TableCell>
                      <TableCell align="right">{i.throughput_per_second.toFixed(3)}/s</TableCell>
                      <TableCell align="right">{formatMs(i.average_latency_ms)}</TableCell>
                      <TableCell align="right">{formatMs(i.p50_latency_ms)}</TableCell>
                      <TableCell align="right">{formatMs(i.p90_latency_ms)}</TableCell>
                      <TableCell align="right">{formatMs(i.p95_latency_ms)}</TableCell>
                      <TableCell align="right">{formatMs(i.p99_latency_ms)}</TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            </Box>
            <Typography variant="caption" color="text.secondary" sx={{ display: 'block', p: 1.5 }}>
              Percentiles: {services.data.percentile_method}.
            </Typography>
          </Card>
        </>
      )}
    </>
  );
}

function ChartCard({ title, subtitle, height = 280, children }: { title: string; subtitle?: string; height?: number; children: React.ReactElement }) {
  return (
    <Card sx={{ height: '100%' }}>
      <CardContent>
        <Stack spacing={0} sx={{ mb: 1 }}>
          <Typography variant="h6">{title}</Typography>
          {subtitle && (
            <Typography variant="caption" color="text.secondary">
              {subtitle}
            </Typography>
          )}
        </Stack>
        <Box sx={{ height }}>
          <ResponsiveContainer width="100%" height="100%">
            {children}
          </ResponsiveContainer>
        </Box>
      </CardContent>
    </Card>
  );
}
