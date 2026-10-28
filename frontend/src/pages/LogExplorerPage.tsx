import ExpandMoreIcon from '@mui/icons-material/ExpandMore';
import {
  Box,
  Button,
  Card,
  CardContent,
  Collapse,
  IconButton,
  MenuItem,
  Stack,
  Tab,
  Table,
  TableBody,
  TableCell,
  TableHead,
  TablePagination,
  TableRow,
  Tabs,
  TextField,
  Typography,
} from '@mui/material';
import { useMemo, useState } from 'react';
import { useSearchParams } from 'react-router-dom';
import { api } from '../api/endpoints';
import type { LogRecord, Severity } from '../api/types';
import { SeverityChip } from '../components/Chips';
import { EmptyState, ErrorAlert, LoadingBar } from '../components/AsyncState';
import { Mono, PageHeader, TraceLink } from '../components/Common';
import { useAsync } from '../hooks/useAsync';
import { formatDateTime, minutesAgoIso } from '../utils/format';

const SEVERITIES: Severity[] = ['INFO', 'WARNING', 'ERROR', 'CRITICAL'];
const RANGES = [
  { label: 'Any time', minutes: 0 },
  { label: 'Last 15 min', minutes: 15 },
  { label: 'Last hour', minutes: 60 },
  { label: 'Last 6 hours', minutes: 360 },
  { label: 'Last 24 hours', minutes: 1440 },
];

export default function LogExplorerPage() {
  const [params, setParams] = useSearchParams();
  const [tab, setTab] = useState(0);
  const [page, setPage] = useState(0);
  const [rowsPerPage, setRowsPerPage] = useState(50);

  const severity = params.get('severity') ?? '';
  const service = params.get('service') ?? '';
  const traceId = params.get('trace') ?? '';
  const correlationId = params.get('correlation') ?? '';
  const search = params.get('q') ?? '';
  const range = Number(params.get('range') ?? 60);

  const [draftSearch, setDraftSearch] = useState(search);
  const set = (key: string, value: string) => {
    const next = new URLSearchParams(params);
    if (value) next.set(key, value);
    else next.delete(key);
    setParams(next, { replace: true });
    setPage(0);
  };

  const since = useMemo(() => (range ? minutesAgoIso(range) : undefined), [range, params]); // eslint-disable-line react-hooks/exhaustive-deps
  const services = useAsync(() => api.servicesHealth(1440), []);

  const logs = useAsync(
    () =>
      api.logs({
        severity: severity || undefined,
        service_name: service || undefined,
        trace_id: traceId || undefined,
        correlation_id: correlationId || undefined,
        search: search || undefined,
        start_time: since,
        limit: rowsPerPage,
        offset: page * rowsPerPage,
      }),
    [severity, service, traceId, correlationId, search, since, page, rowsPerPage],
    10000,
    tab === 0,
  );

  const patterns = useAsync(
    () => api.logPatterns({ service_name: service || undefined, severity: severity || 'ERROR', start_time: since, min_count: 2 }),
    [service, severity, since],
    15000,
    tab === 1,
  );

  return (
    <>
      <PageHeader title="Log Explorer" subtitle="Search normalised logs and find repeated errors" />

      <Card sx={{ mb: 2 }}>
        <CardContent>
          <Stack direction={{ xs: 'column', md: 'row' }} spacing={2} flexWrap="wrap" useFlexGap>
            <TextField select size="small" label="Severity" value={severity} onChange={(e) => set('severity', e.target.value)} sx={{ minWidth: 140 }}>
              <MenuItem value="">All</MenuItem>
              {SEVERITIES.map((s) => (
                <MenuItem key={s} value={s}>
                  {s}
                </MenuItem>
              ))}
            </TextField>
            <TextField select size="small" label="Service" value={service} onChange={(e) => set('service', e.target.value)} sx={{ minWidth: 200 }}>
              <MenuItem value="">All services</MenuItem>
              {services.data?.items.map((s) => (
                <MenuItem key={s.service_name} value={s.service_name}>
                  {s.service_name}
                </MenuItem>
              ))}
            </TextField>
            <TextField select size="small" label="Time range" value={range} onChange={(e) => set('range', e.target.value)} sx={{ minWidth: 150 }}>
              {RANGES.map((r) => (
                <MenuItem key={r.minutes} value={r.minutes}>
                  {r.label}
                </MenuItem>
              ))}
            </TextField>
            <TextField size="small" label="Trace ID" value={traceId} onChange={(e) => set('trace', e.target.value.trim())} sx={{ minWidth: 260 }} />
            <TextField size="small" label="Correlation ID" value={correlationId} onChange={(e) => set('correlation', e.target.value.trim())} sx={{ minWidth: 260 }} />
            <form
              onSubmit={(e) => {
                e.preventDefault();
                set('q', draftSearch.trim());
              }}
            >
              <Stack direction="row" spacing={1}>
                <TextField size="small" label="Message contains" value={draftSearch} onChange={(e) => setDraftSearch(e.target.value)} />
                <Button type="submit" variant="contained">
                  Search
                </Button>
              </Stack>
            </form>
            <Button
              onClick={() => {
                setParams({}, { replace: true });
                setDraftSearch('');
              }}
            >
              Reset
            </Button>
          </Stack>
        </CardContent>
      </Card>

      <Card>
        <Tabs value={tab} onChange={(_, v: number) => setTab(v)} sx={{ borderBottom: 1, borderColor: 'divider', px: 2 }}>
          <Tab label="Logs" />
          <Tab label="Repeated error patterns" />
        </Tabs>

        {tab === 0 && (
          <>
            <LoadingBar loading={logs.loading && !logs.data} />
            {logs.error && <Box sx={{ p: 2 }}><ErrorAlert error={logs.error} onRetry={logs.reload} /></Box>}
            {logs.data && logs.data.items.length === 0 && <EmptyState>No logs match these filters.</EmptyState>}
            {!!logs.data?.items.length && (
              <Box sx={{ overflowX: 'auto' }}>
                <Table size="small">
                  <TableHead>
                    <TableRow>
                      <TableCell />
                      <TableCell>Time</TableCell>
                      <TableCell>Severity</TableCell>
                      <TableCell>Service</TableCell>
                      <TableCell>Message</TableCell>
                      <TableCell>Trace</TableCell>
                    </TableRow>
                  </TableHead>
                  <TableBody>
                    {logs.data.items.map((l) => (
                      <LogRow key={l.id} log={l} />
                    ))}
                  </TableBody>
                </Table>
              </Box>
            )}
            <TablePagination
              component="div"
              count={logs.data?.total ?? 0}
              page={page}
              onPageChange={(_, p) => setPage(p)}
              rowsPerPage={rowsPerPage}
              onRowsPerPageChange={(e) => {
                setRowsPerPage(Number(e.target.value));
                setPage(0);
              }}
              rowsPerPageOptions={[25, 50, 100, 200]}
            />
          </>
        )}

        {tab === 1 && (
          <>
            <LoadingBar loading={patterns.loading && !patterns.data} />
            {patterns.error && <Box sx={{ p: 2 }}><ErrorAlert error={patterns.error} onRetry={patterns.reload} /></Box>}
            {patterns.data && patterns.data.items.length === 0 && (
              <EmptyState>No message repeated at least twice in this window (severity {severity || 'ERROR'}).</EmptyState>
            )}
            {!!patterns.data?.items.length && (
              <Box sx={{ overflowX: 'auto' }}>
                <Table size="small">
                  <TableHead>
                    <TableRow>
                      <TableCell align="right">Count</TableCell>
                      <TableCell>Service</TableCell>
                      <TableCell>Severity</TableCell>
                      <TableCell>Example message</TableCell>
                      <TableCell>First / last seen</TableCell>
                      <TableCell>Example traces</TableCell>
                    </TableRow>
                  </TableHead>
                  <TableBody>
                    {patterns.data.items.map((p) => (
                      <TableRow key={p.fingerprint + p.service_name}>
                        <TableCell align="right" sx={{ fontWeight: 700 }}>{p.occurrence_count}×</TableCell>
                        <TableCell>{p.service_name}</TableCell>
                        <TableCell><SeverityChip severity={p.severity} /></TableCell>
                        <TableCell>{p.sample_message}</TableCell>
                        <TableCell sx={{ whiteSpace: 'nowrap' }}>
                          {formatDateTime(p.first_seen)}
                          <br />
                          {formatDateTime(p.last_seen)}
                        </TableCell>
                        <TableCell>
                          <Stack>{p.example_trace_ids.map((t) => <TraceLink key={t} traceId={t} />)}</Stack>
                        </TableCell>
                      </TableRow>
                    ))}
                  </TableBody>
                </Table>
              </Box>
            )}
            <Typography variant="caption" color="text.secondary" sx={{ display: 'block', p: 2 }}>
              Messages are grouped after masking ids, numbers and quoted values, so "Order 17 failed" and "Order 18 failed" count as one pattern.
            </Typography>
          </>
        )}
      </Card>
    </>
  );
}

function LogRow({ log }: { log: LogRecord }) {
  const [open, setOpen] = useState(false);
  return (
    <>
      <TableRow hover>
        <TableCell sx={{ width: 40, p: 0.5 }}>
          <IconButton size="small" onClick={() => setOpen(!open)} aria-label="Expand" sx={{ transform: open ? 'rotate(180deg)' : 'none', transition: '150ms' }}>
            <ExpandMoreIcon fontSize="small" />
          </IconButton>
        </TableCell>
        <TableCell sx={{ whiteSpace: 'nowrap' }}>{formatDateTime(log.timestamp)}</TableCell>
        <TableCell><SeverityChip severity={log.severity} /></TableCell>
        <TableCell>{log.service_name}</TableCell>
        <TableCell sx={{ maxWidth: 520, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: open ? 'normal' : 'nowrap' }}>{log.message}</TableCell>
        <TableCell>{log.trace_id ? <TraceLink traceId={log.trace_id} /> : '–'}</TableCell>
      </TableRow>
      <TableRow>
        <TableCell colSpan={6} sx={{ p: 0, border: open ? undefined : 0 }}>
          <Collapse in={open} unmountOnExit>
            <Box sx={{ p: 2, bgcolor: 'action.hover' }}>
              <Typography variant="body2" sx={{ whiteSpace: 'pre-wrap', mb: 1 }}>{log.message}</Typography>
              <Typography variant="caption" component="div">Event ID: <Mono>{log.event_id}</Mono></Typography>
              <Typography variant="caption" component="div">Span ID: <Mono>{log.span_id ?? '–'}</Mono></Typography>
              <Typography variant="caption" component="div">Correlation ID: <Mono>{log.correlation_id ?? '–'}</Mono></Typography>
            </Box>
          </Collapse>
        </TableCell>
      </TableRow>
    </>
  );
}
