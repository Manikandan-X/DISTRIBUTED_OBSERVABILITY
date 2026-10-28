import { Box, Card, CardContent, Chip, FormControlLabel, LinearProgress, Stack, Switch, Table, TableBody, TableCell, TableHead, TableRow, Typography } from '@mui/material';
import Grid from '@mui/material/Grid2';
import { useState } from 'react';
import { Link } from 'react-router-dom';
import { api } from '../api/endpoints';
import { AlertSeverityChip, TraceStatusChip } from '../components/Chips';
import { EmptyState, ErrorAlert, LoadingBar, PartialWarnings } from '../components/AsyncState';
import { PageHeader, StatCard, TimeWindowSelect, TraceLink } from '../components/Common';
import { useAsync } from '../hooks/useAsync';
import { ALERT_TYPE_LABELS, formatAlertValue, formatDateTime, formatMs, formatNumber, formatPercent } from '../utils/format';

export default function OverviewPage() {
  const [minutes, setMinutes] = useState(60);
  const [auto, setAuto] = useState(true);
  const poll = auto ? 15000 : 0;

  const overview = useAsync(() => api.overview(minutes), [minutes], poll);
  const services = useAsync(() => api.servicesHealth(minutes), [minutes], poll);
  const alerts = useAsync(() => api.alerts({ status: 'active', limit: 5 }), [], poll);
  const errorTraces = useAsync(() => api.traces({ status: 'error', limit: 5 }), [], poll);

  const o = overview.data;
  const errorTone = !o ? 'default' : o.error_rate_percent >= 20 ? 'error' : o.error_rate_percent > 0 ? 'warning' : 'success';

  return (
    <>
      <PageHeader
        title="Overview"
        subtitle="Health of every service that reports telemetry"
        actions={
          <>
            <FormControlLabel control={<Switch checked={auto} onChange={(e) => setAuto(e.target.checked)} />} label="Auto-refresh (15 s)" />
            <TimeWindowSelect value={minutes} onChange={setMinutes} />
          </>
        }
      />
      <LoadingBar loading={overview.loading && !o} />
      {overview.error && <ErrorAlert error={overview.error} onRetry={overview.reload} />}
      {o && <PartialWarnings partial={o.partial} warnings={o.warnings} />}

      <Grid container spacing={2} sx={{ mb: 3 }}>
        <Grid size={{ xs: 6, md: 4, lg: 2 }}>
          <StatCard label="Total requests" value={formatNumber(o?.total_requests)} hint="observed traces" />
        </Grid>
        <Grid size={{ xs: 6, md: 4, lg: 2 }}>
          <StatCard label="Error rate" value={formatPercent(o?.error_rate_percent)} tone={errorTone} />
        </Grid>
        <Grid size={{ xs: 6, md: 4, lg: 2 }}>
          <StatCard label="Avg latency" value={formatMs(o?.average_latency_ms)} />
        </Grid>
        <Grid size={{ xs: 6, md: 4, lg: 2 }}>
          <StatCard label="p95 / p99 latency" value={formatMs(o?.p95_latency_ms)} hint={`p99 ${formatMs(o?.p99_latency_ms)}`} />
        </Grid>
        <Grid size={{ xs: 6, md: 4, lg: 2 }}>
          <StatCard label="Services with errors" value={o?.services_reporting_errors ?? '–'} tone={o && o.services_reporting_errors > 0 ? 'warning' : 'default'} />
        </Grid>
        <Grid size={{ xs: 6, md: 4, lg: 2 }}>
          <StatCard label="Active alerts" value={o?.active_alerts ?? '–'} tone={o && o.active_alerts > 0 ? 'error' : 'success'} />
        </Grid>
      </Grid>

      <Grid container spacing={2}>
        <Grid size={{ xs: 12, lg: 7 }}>
          <Card>
            <CardContent>
              <Typography variant="h6" gutterBottom>
                Services
              </Typography>
              <LoadingBar loading={services.loading && !services.data} />
              {services.error && <ErrorAlert error={services.error} onRetry={services.reload} />}
              {services.data && services.data.items.length === 0 && <EmptyState>No service has reported telemetry in this window.</EmptyState>}
              {!!services.data?.items.length && (
                <Table size="small">
                  <TableHead>
                    <TableRow>
                      <TableCell>Service</TableCell>
                      <TableCell align="right">Requests</TableCell>
                      <TableCell sx={{ width: 180 }}>Error rate</TableCell>
                      <TableCell align="right">Avg</TableCell>
                      <TableCell align="right">p95</TableCell>
                    </TableRow>
                  </TableHead>
                  <TableBody>
                    {services.data.items.map((s) => (
                      <TableRow key={s.service_name} hover>
                        <TableCell sx={{ fontWeight: 600 }}>
                          <Link to={`/dependencies?service=${s.service_name}`} style={{ color: 'inherit' }}>
                            {s.service_name}
                          </Link>
                        </TableCell>
                        <TableCell align="right">{formatNumber(s.request_count)}</TableCell>
                        <TableCell>
                          <Stack direction="row" spacing={1} alignItems="center">
                            <LinearProgress
                              variant="determinate"
                              value={Math.min(100, s.error_rate_percent)}
                              color={s.error_rate_percent >= 20 ? 'error' : s.error_rate_percent > 0 ? 'warning' : 'success'}
                              sx={{ flexGrow: 1, height: 8, borderRadius: 4 }}
                            />
                            <Typography variant="caption" sx={{ width: 48, textAlign: 'right' }}>
                              {formatPercent(s.error_rate_percent)}
                            </Typography>
                          </Stack>
                        </TableCell>
                        <TableCell align="right">{formatMs(s.average_latency_ms)}</TableCell>
                        <TableCell align="right">{formatMs(s.p95_latency_ms)}</TableCell>
                      </TableRow>
                    ))}
                  </TableBody>
                </Table>
              )}
            </CardContent>
          </Card>
        </Grid>

        <Grid size={{ xs: 12, lg: 5 }}>
          <Stack spacing={2}>
            <Card>
              <CardContent>
                <Stack direction="row" justifyContent="space-between" alignItems="center">
                  <Typography variant="h6">Active alerts</Typography>
                  <Link to="/alerts">View all</Link>
                </Stack>
                {alerts.error && <ErrorAlert error={alerts.error} onRetry={alerts.reload} />}
                {alerts.data && alerts.data.items.length === 0 && <EmptyState>No active alerts.</EmptyState>}
                {alerts.data?.items.map((a) => (
                  <Box key={a.id} sx={{ py: 1, borderBottom: '1px solid', borderColor: 'divider' }}>
                    <Stack direction="row" spacing={1} alignItems="center">
                      <AlertSeverityChip severity={a.severity} />
                      <Typography sx={{ fontWeight: 600 }}>{a.service_name}</Typography>
                    </Stack>
                    <Typography variant="body2" color="text.secondary">
                      {ALERT_TYPE_LABELS[a.alert_type] ?? a.alert_type}: {formatAlertValue(a.alert_type, a.measured_value)} (limit {formatAlertValue(a.alert_type, a.threshold_value)}) · seen {a.occurrence_count}×
                    </Typography>
                  </Box>
                ))}
              </CardContent>
            </Card>

            <Card>
              <CardContent>
                <Stack direction="row" justifyContent="space-between" alignItems="center">
                  <Typography variant="h6">Latest failed requests</Typography>
                  <Link to="/traces?status=error">View all</Link>
                </Stack>
                {errorTraces.error && <ErrorAlert error={errorTraces.error} onRetry={errorTraces.reload} />}
                {errorTraces.data && errorTraces.data.items.length === 0 && <EmptyState>No failed requests.</EmptyState>}
                {errorTraces.data?.items.map((t) => (
                  <Stack key={t.trace_id} direction="row" spacing={1} alignItems="center" sx={{ py: 1, borderBottom: '1px solid', borderColor: 'divider' }}>
                    <TraceStatusChip status={t.status} />
                    <TraceLink traceId={t.trace_id} />
                    <Chip size="small" label={t.root_service} variant="outlined" />
                    <Typography variant="caption" color="text.secondary" sx={{ ml: 'auto' }}>
                      {formatDateTime(t.start_time)}
                    </Typography>
                  </Stack>
                ))}
              </CardContent>
            </Card>
          </Stack>
        </Grid>
      </Grid>
    </>
  );
}
