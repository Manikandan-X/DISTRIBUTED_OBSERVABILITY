import ArrowBackIcon from '@mui/icons-material/ArrowBack';
import TroubleshootIcon from '@mui/icons-material/Troubleshoot';
import {
  Alert,
  Box,
  Button,
  Card,
  CardContent,
  Chip,
  LinearProgress,
  MenuItem,
  Stack,
  Table,
  TableBody,
  TableCell,
  TableHead,
  TablePagination,
  TableRow,
  TextField,
  Typography,
} from '@mui/material';
import Grid from '@mui/material/Grid2';
import { useState } from 'react';
import { Bar, BarChart, CartesianGrid, Cell, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts';
import { Link, useNavigate, useParams, useSearchParams } from 'react-router-dom';
import { toUiError } from '../api/client';
import { api } from '../api/endpoints';
import type { DiagnosticDetail, EvidenceItem } from '../api/types';
import { ClassificationChip, RootCauseChip } from '../components/Chips';
import { EmptyState, ErrorAlert, LoadingBar, PartialWarnings } from '../components/AsyncState';
import { Mono, PageHeader, TraceLink } from '../components/Common';
import { useAsync } from '../hooks/useAsync';
import { serviceColor } from '../theme';
import { formatDateTime, formatMs, formatPercent, formatTime } from '../utils/format';

export default function RootCausePage() {
  const { reportId } = useParams();
  return reportId ? <ReportDetail id={Number(reportId)} /> : <ReportList />;
}

// =================================================================== list
function ReportList() {
  const navigate = useNavigate();
  const [params] = useSearchParams();
  const [traceId, setTraceId] = useState(params.get('trace') ?? '');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [status, setStatus] = useState('');
  const [page, setPage] = useState(0);
  const [rowsPerPage, setRowsPerPage] = useState(25);

  const reports = useAsync(
    () => api.diagnostics({ root_cause_status: status || undefined, limit: rowsPerPage, offset: page * rowsPerPage }),
    [status, page, rowsPerPage],
    15000,
  );

  const run = async () => {
    setBusy(true);
    setError(null);
    try {
      const report = await api.analyze(traceId.trim());
      navigate(`/diagnostics/${report.id}`);
    } catch (err) {
      const ui = toUiError(err);
      setError(ui.status === 404 ? 'That trace does not exist (yet). Check the trace ID.' : ui.message);
    } finally {
      setBusy(false);
    }
  };

  return (
    <>
      <PageHeader title="Root-Cause Analysis" subtitle="Deterministic, evidence-based diagnostics for failed or slow requests" />

      <Card sx={{ mb: 2 }}>
        <CardContent>
          <Typography variant="h6" gutterBottom>
            Analyse a trace
          </Typography>
          <Stack direction={{ xs: 'column', md: 'row' }} spacing={2}>
            <TextField size="small" fullWidth label="Trace ID" value={traceId} onChange={(e) => setTraceId(e.target.value)} />
            <Button variant="contained" startIcon={<TroubleshootIcon />} onClick={run} disabled={busy || !traceId.trim()} sx={{ whiteSpace: 'nowrap' }}>
              {busy ? 'Analysing…' : 'Run analysis'}
            </Button>
          </Stack>
          {error && <Alert severity="error" sx={{ mt: 2 }}>{error}</Alert>}
          <Typography variant="caption" color="text.secondary" sx={{ display: 'block', mt: 1 }}>
            Tip: find a failed request in the <Link to="/traces?status=error">Trace Explorer</Link>.
          </Typography>
        </CardContent>
      </Card>

      <Card>
        <Stack direction="row" justifyContent="space-between" alignItems="center" sx={{ p: 2 }}>
          <Typography variant="h6">Reports</Typography>
          <TextField select size="small" label="Verdict" value={status} onChange={(e) => { setStatus(e.target.value); setPage(0); }} sx={{ minWidth: 190 }}>
            <MenuItem value="">All</MenuItem>
            <MenuItem value="confirmed">Confirmed</MenuItem>
            <MenuItem value="probable">Probable</MenuItem>
            <MenuItem value="inconclusive">Inconclusive</MenuItem>
            <MenuItem value="no_issue_detected">No issue detected</MenuItem>
          </TextField>
        </Stack>
        <LoadingBar loading={reports.loading && !reports.data} />
        {reports.error && <Box sx={{ p: 2 }}><ErrorAlert error={reports.error} onRetry={reports.reload} /></Box>}
        {reports.data && reports.data.items.length === 0 && <EmptyState>No reports yet.</EmptyState>}
        {!!reports.data?.items.length && (
          <Box sx={{ overflowX: 'auto' }}>
            <Table size="small">
              <TableHead>
                <TableRow>
                  <TableCell>Verdict</TableCell>
                  <TableCell>Affected service</TableCell>
                  <TableCell>Severity</TableCell>
                  <TableCell>Confidence</TableCell>
                  <TableCell>Trace</TableCell>
                  <TableCell>Created</TableCell>
                </TableRow>
              </TableHead>
              <TableBody>
                {reports.data.items.map((r) => (
                  <TableRow key={r.id} hover sx={{ cursor: 'pointer' }} onClick={() => navigate(`/diagnostics/${r.id}`)}>
                    <TableCell><RootCauseChip status={r.root_cause_status} /></TableCell>
                    <TableCell sx={{ fontWeight: 600 }}>{r.affected_service}</TableCell>
                    <TableCell>{r.severity}</TableCell>
                    <TableCell>{formatPercent(r.confidence_level * 100, 0)}</TableCell>
                    <TableCell onClick={(e) => e.stopPropagation()}><TraceLink traceId={r.trace_id} /></TableCell>
                    <TableCell>{formatDateTime(r.created_at)}</TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </Box>
        )}
        <TablePagination
          component="div"
          count={reports.data?.total ?? 0}
          page={page}
          onPageChange={(_, p) => setPage(p)}
          rowsPerPage={rowsPerPage}
          onRowsPerPageChange={(e) => { setRowsPerPage(Number(e.target.value)); setPage(0); }}
          rowsPerPageOptions={[10, 25, 50]}
        />
      </Card>
    </>
  );
}

// ================================================================= detail
const EVIDENCE_LABELS: Record<string, string> = {
  trace_span: 'Failing / involved spans',
  log: 'Related logs',
  metric: 'Metric evidence',
  alert: 'Active alerts',
  latency: 'Latency contribution',
};

function ReportDetail({ id }: { id: number }) {
  const report = useAsync(() => api.diagnostic(id), [id]);
  const r = report.data;

  return (
    <>
      <Button component={Link} to="/diagnostics" startIcon={<ArrowBackIcon />} sx={{ mb: 1 }}>
        All reports
      </Button>
      <LoadingBar loading={report.loading && !r} />
      {report.error && <ErrorAlert error={report.error} onRetry={report.reload} />}
      {r && <ReportBody report={r} />}
    </>
  );
}

function ReportBody({ report: r }: { report: DiagnosticDetail }) {
  const ev = r.evidence;
  const grouped = r.evidence_items.reduce<Record<string, EvidenceItem[]>>((acc, item) => {
    (acc[item.evidence_type] ??= []).push(item);
    return acc;
  }, {});
  const honest = r.root_cause_status === 'inconclusive' || r.root_cause_status === 'probable';

  return (
    <>
      <PageHeader title={`Report #${r.id}`} subtitle={`Created ${formatDateTime(r.created_at)} · rules v${r.rules_version ?? '?'}`} />
      <PartialWarnings warnings={r.warnings} partial={r.warnings.length > 0} />

      <Card sx={{ mb: 2, borderLeft: 6, borderLeftColor: r.root_cause_status === 'confirmed' ? 'error.main' : r.root_cause_status === 'no_issue_detected' ? 'success.main' : 'warning.main' }}>
        <CardContent>
          <Stack direction={{ xs: 'column', md: 'row' }} spacing={2} justifyContent="space-between">
            <Box sx={{ flexGrow: 1 }}>
              <Stack direction="row" spacing={1.5} alignItems="center" flexWrap="wrap" useFlexGap sx={{ mb: 1 }}>
                <RootCauseChip status={r.root_cause_status} />
                <Chip label={`Severity ${r.severity}`} variant="outlined" color={r.severity === 'HIGH' ? 'error' : r.severity === 'MEDIUM' ? 'warning' : 'default'} />
                <Typography variant="body2">
                  Trace: <TraceLink traceId={r.trace_id} full />
                </Typography>
              </Stack>
              <Typography variant="overline" color="text.secondary">
                Suspected affected service
              </Typography>
              <Typography variant="h4" sx={{ fontWeight: 700, color: serviceColor(r.affected_service) }}>
                {r.affected_service}
              </Typography>
              <Typography sx={{ mt: 1 }}>{r.diagnosis}</Typography>
            </Box>
            <Box sx={{ minWidth: 200 }}>
              <Typography variant="overline" color="text.secondary">
                Confidence
              </Typography>
              <Typography variant="h4">{formatPercent(r.confidence_level * 100, 0)}</Typography>
              <LinearProgress variant="determinate" value={r.confidence_level * 100} color={r.confidence_level >= 0.8 ? 'success' : 'warning'} sx={{ height: 8, borderRadius: 4 }} />
            </Box>
          </Stack>
        </CardContent>
      </Card>

      {honest && (
        <Alert severity="warning" sx={{ mb: 2 }}>
          The telemetry is not strong enough to confirm a root cause. Treat the service above as a lead to investigate, not a conclusion.
        </Alert>
      )}
      {ev && ev.limitations.length > 0 && (
        <Alert severity="info" sx={{ mb: 2 }}>
          <b>Limitations of this analysis</b>
          <ul style={{ margin: '4px 0 0', paddingLeft: 18 }}>
            {ev.limitations.map((l) => <li key={l}>{l}</li>)}
          </ul>
        </Alert>
      )}

      {ev && (
        <Grid container spacing={2} sx={{ mb: 2 }}>
          <Grid size={{ xs: 12, lg: 6 }}>
            <Card sx={{ height: '100%' }}>
              <CardContent>
                <Typography variant="h6" gutterBottom>Ranked services</Typography>
                {ev.ranked_services.length === 0 && <EmptyState>No service stood out.</EmptyState>}
                <Stack spacing={1.5}>
                  {ev.ranked_services.map((s, i) => (
                    <Box key={s.service_name} sx={{ p: 1.5, border: '1px solid', borderColor: 'divider', borderRadius: 2 }}>
                      <Stack direction="row" spacing={1} alignItems="center">
                        <Typography sx={{ fontWeight: 700 }}>#{i + 1} {s.service_name}</Typography>
                        <ClassificationChip value={s.classification} />
                        <Typography variant="caption" color="text.secondary" sx={{ ml: 'auto' }}>score {s.score.toFixed(0)}</Typography>
                      </Stack>
                      <Box component="ul" sx={{ m: 0, mt: 0.5, pl: 2.5 }}>
                        {s.reasons.map((reason) => (
                          <Typography key={reason} component="li" variant="body2">{reason}</Typography>
                        ))}
                      </Box>
                    </Box>
                  ))}
                </Stack>
                <Typography variant="caption" color="text.secondary" sx={{ display: 'block', mt: 1 }}>
                  <b>confirmed</b> = observed in the trace · <b>potential</b> = corroborating signals only · <b>symptom</b> = failed because something it called failed.
                </Typography>
              </CardContent>
            </Card>
          </Grid>

          <Grid size={{ xs: 12, lg: 6 }}>
            <Card sx={{ height: '100%' }}>
              <CardContent>
                <Typography variant="h6" gutterBottom>Failure timeline</Typography>
                {ev.failure_timeline.length === 0 && <EmptyState>No failed spans in this trace.</EmptyState>}
                <Stack spacing={0}>
                  {ev.failure_timeline.map((t, i) => (
                    <Stack key={t.span_id} direction="row" spacing={1.5}>
                      <Stack alignItems="center">
                        <Box sx={{ width: 12, height: 12, borderRadius: '50%', mt: 0.6, bgcolor: t.event === 'failure origin' ? 'error.main' : 'warning.main' }} />
                        {i < ev.failure_timeline.length - 1 && <Box sx={{ width: 2, flexGrow: 1, bgcolor: 'divider' }} />}
                      </Stack>
                      <Box sx={{ pb: 1.5 }}>
                        <Typography variant="body2" sx={{ fontWeight: 600 }}>
                          {t.service_name} · {t.event}
                        </Typography>
                        <Typography variant="caption" color="text.secondary">
                          {formatTime(t.timestamp)} · span <Mono>{t.span_id}</Mono>
                        </Typography>
                      </Box>
                    </Stack>
                  ))}
                </Stack>
                {ev.request_path.length > 0 && (
                  <Typography variant="body2" sx={{ mt: 1 }}>
                    <b>Request path:</b> {ev.request_path.join(' → ')}
                  </Typography>
                )}
              </CardContent>
            </Card>
          </Grid>

          <Grid size={{ xs: 12, lg: 6 }}>
            <Card sx={{ height: '100%' }}>
              <CardContent>
                <Typography variant="h6">Latency contribution</Typography>
                <Box sx={{ height: 40 + ev.latency_contribution.length * 44, mt: 1 }}>
                  <ResponsiveContainer width="100%" height="100%">
                    <BarChart data={ev.latency_contribution} layout="vertical" margin={{ left: 20, right: 30 }}>
                      <CartesianGrid strokeDasharray="3 3" horizontal={false} />
                      <XAxis type="number" tickFormatter={(v: number) => formatMs(v)} />
                      <YAxis type="category" dataKey="service_name" width={150} />
                      <Tooltip formatter={(v: number) => formatMs(v)} />
                      <Bar dataKey="self_time_ms" name="Self time" radius={[0, 4, 4, 0]} isAnimationActive={false}>
                        {ev.latency_contribution.map((s) => <Cell key={s.service_name} fill={serviceColor(s.service_name)} />)}
                      </Bar>
                    </BarChart>
                  </ResponsiveContainer>
                </Box>
              </CardContent>
            </Card>
          </Grid>

          <Grid size={{ xs: 12, lg: 6 }}>
            <Card sx={{ height: '100%' }}>
              <CardContent>
                <Typography variant="h6" gutterBottom>Related traces</Typography>
                {ev.related_trace_ids.length === 0 ? (
                  <Typography variant="body2" color="text.secondary">No other traces are linked to active alerts for these services.</Typography>
                ) : (
                  <Stack>{ev.related_trace_ids.map((t) => <TraceLink key={t} traceId={t} full />)}</Stack>
                )}
                <Typography variant="body2" sx={{ mt: 2 }}>
                  Spans analysed: <b>{ev.span_count}</b> · failed: <b>{ev.failed_span_count}</b> · error logs: <b>{ev.error_log_count}</b>
                </Typography>
              </CardContent>
            </Card>
          </Grid>
        </Grid>
      )}

      <Card>
        <CardContent>
          <Typography variant="h6" gutterBottom>Supporting evidence</Typography>
          {r.evidence_items.length === 0 && <EmptyState>No evidence items were stored.</EmptyState>}
          {Object.entries(grouped).map(([type, items]) => (
            <Box key={type} sx={{ mb: 2 }}>
              <Typography variant="subtitle2" sx={{ mb: 0.5 }}>{EVIDENCE_LABELS[type] ?? type} ({items.length})</Typography>
              <Table size="small">
                <TableBody>
                  {items.map((item) => (
                    <TableRow key={item.id}>
                      <TableCell sx={{ width: 220, verticalAlign: 'top' }}><Mono>{item.reference_id}</Mono></TableCell>
                      <TableCell sx={{ wordBreak: 'break-word' }}>{item.description}</TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            </Box>
          ))}
        </CardContent>
      </Card>
    </>
  );
}
