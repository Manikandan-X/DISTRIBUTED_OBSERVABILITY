import ArrowBackIcon from '@mui/icons-material/ArrowBack';
import ArrowForwardIcon from '@mui/icons-material/ArrowForward';
import TroubleshootIcon from '@mui/icons-material/Troubleshoot';
import {
  Alert,
  Box,
  Button,
  Card,
  CardContent,
  Chip,
  Stack,
  Tab,
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableRow,
  Tabs,
  Typography,
} from '@mui/material';
import Grid from '@mui/material/Grid2';
import { useEffect, useState } from 'react';
import { Bar, BarChart, CartesianGrid, Cell, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts';
import { Link, useNavigate, useParams } from 'react-router-dom';
import { toUiError } from '../api/client';
import { api } from '../api/endpoints';
import type { Span, TraceDetail } from '../api/types';
import { useAuth } from '../auth/AuthContext';
import { CompletionChip, RootCauseChip, SeverityChip, TraceStatusChip } from '../components/Chips';
import { EmptyState, ErrorAlert, LoadingBar, PartialWarnings } from '../components/AsyncState';
import { Mono, PageHeader } from '../components/Common';
import TraceTimeline from '../components/TraceTimeline';
import { useAsync } from '../hooks/useAsync';
import { serviceColor } from '../theme';
import { formatDateTime, formatMs, formatPercent, formatTime } from '../utils/format';

export default function TraceDetailPage() {
  const { traceId = '' } = useParams();
  const navigate = useNavigate();
  const { can } = useAuth();
  const [tab, setTab] = useState(0);
  const [selected, setSelected] = useState<Span | null>(null);
  const [analyzing, setAnalyzing] = useState(false);
  const [analyzeError, setAnalyzeError] = useState<string | null>(null);

  const trace = useAsync(() => api.trace(traceId), [traceId], 10000);
  const detail = trace.data;

  // Pre-select the first failed span (that is where the story starts).
  useEffect(() => {
    if (detail && !selected) setSelected(detail.spans.find((s) => s.is_failed) ?? detail.spans[0] ?? null);
  }, [detail, selected]);

  const analyze = async () => {
    setAnalyzing(true);
    setAnalyzeError(null);
    try {
      const report = await api.analyze(traceId);
      navigate(`/diagnostics/${report.id}`);
    } catch (err) {
      setAnalyzeError(toUiError(err).message);
    } finally {
      setAnalyzing(false);
    }
  };

  if (trace.error && !detail) {
    return (
      <>
        <Button component={Link} to="/traces" startIcon={<ArrowBackIcon />} sx={{ mb: 2 }}>
          Back to traces
        </Button>
        <ErrorAlert error={trace.error} onRetry={trace.reload} />
      </>
    );
  }

  return (
    <>
      <Button component={Link} to="/traces" startIcon={<ArrowBackIcon />} sx={{ mb: 1 }}>
        Back to traces
      </Button>
      <PageHeader
        title="Trace"
        subtitle={traceId}
        actions={
          can('analyst') && (
            <Button variant="contained" startIcon={<TroubleshootIcon />} onClick={analyze} disabled={analyzing || !detail}>
              {analyzing ? 'Analysing…' : 'Run root-cause analysis'}
            </Button>
          )
        }
      />
      <LoadingBar loading={trace.loading && !detail} />
      {analyzeError && <Alert severity="error" sx={{ mb: 2 }}>{analyzeError}</Alert>}
      {trace.error && <ErrorAlert error={trace.error} onRetry={trace.reload} />}

      {detail && (
        <>
          <PartialWarnings partial={detail.partial} warnings={detail.warnings} />

          <Card sx={{ mb: 2 }}>
            <CardContent>
              <Stack direction="row" spacing={1.5} alignItems="center" flexWrap="wrap" useFlexGap>
                <TraceStatusChip status={detail.trace.status} />
                <CompletionChip status={detail.trace.completion_status} missing={detail.trace.missing_span_count} />
                <Typography>
                  <b>{formatMs(detail.trace.duration_ms)}</b> total · {detail.spans.length} spans · started {formatDateTime(detail.trace.start_time)}
                </Typography>
                {detail.trace.correlation_id && (
                  <Typography variant="body2" color="text.secondary">
                    Correlation ID: <Mono>{detail.trace.correlation_id}</Mono>
                  </Typography>
                )}
              </Stack>
              <Stack direction="row" spacing={0.5} alignItems="center" flexWrap="wrap" useFlexGap sx={{ mt: 2 }}>
                <Typography variant="body2" color="text.secondary" sx={{ mr: 1 }}>
                  Request path:
                </Typography>
                {detail.request_path.map((svc, i) => (
                  <Stack key={`${svc}-${i}`} direction="row" alignItems="center" spacing={0.5}>
                    {i > 0 && <ArrowForwardIcon fontSize="small" color="disabled" />}
                    <Chip size="small" label={svc} sx={{ bgcolor: serviceColor(svc), color: 'white' }} />
                  </Stack>
                ))}
              </Stack>
              {!detail.is_complete && detail.missing_parent_span_ids.length > 0 && (
                <Alert severity="warning" sx={{ mt: 2 }}>
                  {detail.missing_parent_span_ids.length} parent span(s) never arrived, so part of the request path is unknown:{' '}
                  <Mono>{detail.missing_parent_span_ids.join(', ')}</Mono>
                </Alert>
              )}
            </CardContent>
          </Card>

          <Card sx={{ mb: 2 }}>
            <CardContent>
              <Typography variant="h6" gutterBottom>
                Execution timeline
              </Typography>
              <TraceTimeline spans={detail.spans} selectedSpanId={selected?.span_id} onSelect={setSelected} />
            </CardContent>
          </Card>

          <Grid container spacing={2} sx={{ mb: 2 }}>
            <Grid size={{ xs: 12, md: 6 }}>
              <Card sx={{ height: '100%' }}>
                <CardContent>
                  <Typography variant="h6" gutterBottom>
                    Span details
                  </Typography>
                  {!selected && <EmptyState>Select a span in the timeline.</EmptyState>}
                  {selected && <SpanDetails span={selected} />}
                </CardContent>
              </Card>
            </Grid>
            <Grid size={{ xs: 12, md: 6 }}>
              <Card sx={{ height: '100%' }}>
                <CardContent>
                  <Typography variant="h6">Latency contribution</Typography>
                  <Typography variant="caption" color="text.secondary">
                    Time each service spent in itself (excluding the services it called)
                  </Typography>
                  <Box sx={{ height: 40 + detail.service_latency.length * 44, mt: 1 }}>
                    <ResponsiveContainer width="100%" height="100%">
                      <BarChart data={detail.service_latency} layout="vertical" margin={{ left: 20, right: 30 }}>
                        <CartesianGrid strokeDasharray="3 3" horizontal={false} />
                        <XAxis type="number" tickFormatter={(v: number) => formatMs(v)} />
                        <YAxis type="category" dataKey="service_name" width={150} />
                        <Tooltip formatter={(v: number, _n, item) => [`${formatMs(v)} (${formatPercent((item.payload as { share: number }).share * 100)})`, 'Self time']} />
                        <Bar dataKey="self_time_ms" radius={[0, 4, 4, 0]}>
                          {detail.service_latency.map((s) => (
                            <Cell key={s.service_name} fill={serviceColor(s.service_name)} />
                          ))}
                        </Bar>
                      </BarChart>
                    </ResponsiveContainer>
                  </Box>
                </CardContent>
              </Card>
            </Grid>
          </Grid>

          <Card>
            <Tabs value={tab} onChange={(_, v: number) => setTab(v)} sx={{ borderBottom: 1, borderColor: 'divider', px: 2 }}>
              <Tab label={`Related logs (${detail.logs.length})`} />
              <Tab label={`Diagnostic reports (${detail.diagnostic_reports.length})`} />
              <Tab label={`Spans (${detail.spans.length})`} />
            </Tabs>
            <CardContent>
              {tab === 0 && <LogsTab detail={detail} canView={can('analyst')} />}
              {tab === 1 && <ReportsTab detail={detail} canView={can('analyst')} />}
              {tab === 2 && <SpansTab spans={detail.spans} onSelect={setSelected} />}
            </CardContent>
          </Card>
        </>
      )}
    </>
  );
}

function SpanDetails({ span }: { span: Span }) {
  const rows: [string, React.ReactNode][] = [
    ['Service', span.service_name],
    ['Operation', span.operation_name],
    ['Status', <TraceStatusChip key="s" status={span.status} />],
    ['Duration', formatMs(span.duration_ms)],
    ['Started', formatDateTime(span.start_time)],
    ['Span ID', <Mono key="i">{span.span_id}</Mono>],
    ['Parent span', <Mono key="p">{span.parent_span_id ?? '(root)'}</Mono>],
  ];
  return (
    <>
      <Stack direction="row" spacing={1} sx={{ mb: 1 }}>
        {span.is_failed && <Chip size="small" color="error" label="failed" />}
        {span.is_slow && <Chip size="small" color="warning" label="slow" />}
        {span.is_orphan && <Chip size="small" variant="outlined" label="parent missing" />}
      </Stack>
      <Table size="small">
        <TableBody>
          {rows.map(([k, v]) => (
            <TableRow key={k}>
              <TableCell sx={{ width: 120, color: 'text.secondary' }}>{k}</TableCell>
              <TableCell>{v}</TableCell>
            </TableRow>
          ))}
          {span.error_message && (
            <TableRow>
              <TableCell sx={{ color: 'text.secondary' }}>Error</TableCell>
              <TableCell sx={{ color: 'error.main' }}>{span.error_message}</TableCell>
            </TableRow>
          )}
        </TableBody>
      </Table>
      {span.attributes && Object.keys(span.attributes).length > 0 && (
        <>
          <Typography variant="subtitle2" sx={{ mt: 2 }}>
            Attributes
          </Typography>
          <Box sx={{ fontFamily: 'monospace', fontSize: 12, bgcolor: 'action.hover', p: 1, borderRadius: 1, maxHeight: 160, overflow: 'auto' }}>
            {Object.entries(span.attributes).map(([k, v]) => (
              <div key={k}>
                {k}: {String(v)}
              </div>
            ))}
          </Box>
        </>
      )}
    </>
  );
}

function LogsTab({ detail, canView }: { detail: TraceDetail; canView: boolean }) {
  if (!canView) return <EmptyState>Logs require the analyst role.</EmptyState>;
  if (!detail.logs.length) return <EmptyState>No logs were linked to this trace.</EmptyState>;
  return (
    <Box sx={{ overflowX: 'auto' }}>
      <Table size="small">
        <TableHead>
          <TableRow>
            <TableCell>Time</TableCell>
            <TableCell>Severity</TableCell>
            <TableCell>Service</TableCell>
            <TableCell>Message</TableCell>
          </TableRow>
        </TableHead>
        <TableBody>
          {detail.logs.map((l) => (
            <TableRow key={l.id}>
              <TableCell sx={{ whiteSpace: 'nowrap' }}>{formatTime(l.timestamp)}</TableCell>
              <TableCell><SeverityChip severity={l.severity} /></TableCell>
              <TableCell>{l.service_name}</TableCell>
              <TableCell>{l.message}</TableCell>
            </TableRow>
          ))}
        </TableBody>
      </Table>
    </Box>
  );
}

function ReportsTab({ detail, canView }: { detail: TraceDetail; canView: boolean }) {
  if (!canView) return <EmptyState>Diagnostic reports require the analyst role.</EmptyState>;
  if (!detail.diagnostic_reports.length) return <EmptyState>No analysis has been run for this trace yet.</EmptyState>;
  return (
    <Stack spacing={1}>
      {detail.diagnostic_reports.map((r) => (
        <Stack key={r.id} direction="row" spacing={2} alignItems="center" component={Link} to={`/diagnostics/${r.id}`} sx={{ textDecoration: 'none', color: 'inherit', p: 1, borderRadius: 1, '&:hover': { bgcolor: 'action.hover' } }}>
          <RootCauseChip status={r.root_cause_status} />
          <Typography sx={{ fontWeight: 600 }}>{r.affected_service}</Typography>
          <Typography variant="body2" color="text.secondary" sx={{ flexGrow: 1 }}>
            {r.diagnosis}
          </Typography>
          <Typography variant="caption">{formatDateTime(r.created_at)}</Typography>
        </Stack>
      ))}
    </Stack>
  );
}

function SpansTab({ spans, onSelect }: { spans: Span[]; onSelect: (s: Span) => void }) {
  return (
    <Box sx={{ overflowX: 'auto' }}>
      <Table size="small">
        <TableHead>
          <TableRow>
            <TableCell>Service</TableCell>
            <TableCell>Operation</TableCell>
            <TableCell>Status</TableCell>
            <TableCell align="right">Duration</TableCell>
            <TableCell>Span ID</TableCell>
            <TableCell>Parent</TableCell>
          </TableRow>
        </TableHead>
        <TableBody>
          {spans.map((s) => (
            <TableRow key={s.span_id} hover sx={{ cursor: 'pointer' }} onClick={() => onSelect(s)}>
              <TableCell sx={{ pl: `${16 + s.depth * 12}px` }}>{s.service_name}</TableCell>
              <TableCell>{s.operation_name}</TableCell>
              <TableCell><TraceStatusChip status={s.status} /></TableCell>
              <TableCell align="right">{formatMs(s.duration_ms)}</TableCell>
              <TableCell><Mono>{s.span_id}</Mono></TableCell>
              <TableCell><Mono>{s.parent_span_id ?? '–'}</Mono></TableCell>
            </TableRow>
          ))}
        </TableBody>
      </Table>
    </Box>
  );
}
