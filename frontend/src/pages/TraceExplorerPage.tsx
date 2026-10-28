import SearchIcon from '@mui/icons-material/Search';
import {
  Box,
  Button,
  Card,
  CardContent,
  InputAdornment,
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
import { useState, type FormEvent } from 'react';
import { useNavigate, useSearchParams } from 'react-router-dom';
import { api } from '../api/endpoints';
import { CompletionChip, TraceStatusChip } from '../components/Chips';
import { EmptyState, ErrorAlert, LoadingBar } from '../components/AsyncState';
import { Mono, PageHeader } from '../components/Common';
import { useAsync } from '../hooks/useAsync';
import { formatDateTime, formatMs } from '../utils/format';

type SearchKind = 'trace_id' | 'correlation_id';

export default function TraceExplorerPage() {
  const navigate = useNavigate();
  const [params, setParams] = useSearchParams();

  const [kind, setKind] = useState<SearchKind>('trace_id');
  const [term, setTerm] = useState('');
  const status = params.get('status') ?? '';
  const completion = params.get('completion') ?? '';
  const service = params.get('service') ?? '';
  const [page, setPage] = useState(0);
  const [rowsPerPage, setRowsPerPage] = useState(25);
  const applied = params.get('q') ?? '';
  const appliedKind = (params.get('kind') as SearchKind | null) ?? 'trace_id';

  const traces = useAsync(
    () =>
      api.traces({
        status: status || undefined,
        completion_status: completion || undefined,
        service_name: service || undefined,
        trace_id: applied && appliedKind === 'trace_id' ? applied : undefined,
        correlation_id: applied && appliedKind === 'correlation_id' ? applied : undefined,
        limit: rowsPerPage,
        offset: page * rowsPerPage,
      }),
    [status, completion, service, applied, appliedKind, page, rowsPerPage],
    10000,
  );

  const update = (key: string, value: string) => {
    const next = new URLSearchParams(params);
    if (value) next.set(key, value);
    else next.delete(key);
    setParams(next, { replace: true });
    setPage(0);
  };

  const search = (e: FormEvent) => {
    e.preventDefault();
    const next = new URLSearchParams(params);
    const value = term.trim();
    if (value) {
      next.set('q', value);
      next.set('kind', kind);
    } else {
      next.delete('q');
      next.delete('kind');
    }
    setParams(next, { replace: true });
    setPage(0);
  };

  return (
    <>
      <PageHeader title="Trace Explorer" subtitle="Find a request and follow it across services" />

      <Card sx={{ mb: 2 }}>
        <CardContent>
          <form onSubmit={search}>
            <Stack direction={{ xs: 'column', md: 'row' }} spacing={2}>
              <TextField select size="small" label="Search by" value={kind} onChange={(e) => setKind(e.target.value as SearchKind)} sx={{ minWidth: 170 }}>
                <MenuItem value="trace_id">Trace ID</MenuItem>
                <MenuItem value="correlation_id">Correlation ID</MenuItem>
              </TextField>
              <TextField
                size="small"
                fullWidth
                placeholder={kind === 'trace_id' ? 'e.g. 7ddfe5d7ef4478cdf50a5eae24e109b0' : 'e.g. 7ddc9b860a374600a6acf64dafd773d4'}
                value={term}
                onChange={(e) => setTerm(e.target.value)}
                slotProps={{ input: { startAdornment: <InputAdornment position="start"><SearchIcon /></InputAdornment> } }}
              />
              <Button type="submit" variant="contained">
                Search
              </Button>
              {applied && (
                <Button
                  onClick={() => {
                    setTerm('');
                    update('q', '');
                    update('kind', '');
                  }}
                >
                  Clear
                </Button>
              )}
            </Stack>
          </form>
          <Stack direction={{ xs: 'column', md: 'row' }} spacing={2} sx={{ mt: 2 }}>
            <TextField select size="small" label="Status" value={status} onChange={(e) => update('status', e.target.value)} sx={{ minWidth: 160 }}>
              <MenuItem value="">All</MenuItem>
              <MenuItem value="error">Failed</MenuItem>
              <MenuItem value="ok">OK</MenuItem>
            </TextField>
            <TextField select size="small" label="Completion" value={completion} onChange={(e) => update('completion', e.target.value)} sx={{ minWidth: 170 }}>
              <MenuItem value="">All</MenuItem>
              <MenuItem value="complete">Complete</MenuItem>
              <MenuItem value="incomplete">Incomplete (missing spans)</MenuItem>
              <MenuItem value="in_progress">In progress</MenuItem>
            </TextField>
            <TextField size="small" label="Root service" value={service} onChange={(e) => update('service', e.target.value)} sx={{ minWidth: 200 }} />
          </Stack>
        </CardContent>
      </Card>

      <LoadingBar loading={traces.loading && !traces.data} />
      {traces.error && <ErrorAlert error={traces.error} onRetry={traces.reload} />}

      <Card>
        {traces.data && traces.data.items.length === 0 && <EmptyState>No traces match these filters.</EmptyState>}
        {!!traces.data?.items.length && (
          <Box sx={{ overflowX: 'auto' }}>
            <Table size="small">
              <TableHead>
                <TableRow>
                  <TableCell>Status</TableCell>
                  <TableCell>Trace ID</TableCell>
                  <TableCell>Root service</TableCell>
                  <TableCell>Started</TableCell>
                  <TableCell align="right">Duration</TableCell>
                  <TableCell align="right">Spans</TableCell>
                  <TableCell>Completion</TableCell>
                  <TableCell>Correlation ID</TableCell>
                </TableRow>
              </TableHead>
              <TableBody>
                {traces.data.items.map((t) => (
                  <TableRow key={t.trace_id} hover sx={{ cursor: 'pointer' }} onClick={() => navigate(`/traces/${t.trace_id}`)}>
                    <TableCell><TraceStatusChip status={t.status} /></TableCell>
                    <TableCell><Mono>{t.trace_id}</Mono></TableCell>
                    <TableCell>{t.root_service}</TableCell>
                    <TableCell>{formatDateTime(t.start_time)}</TableCell>
                    <TableCell align="right">{formatMs(t.duration_ms)}</TableCell>
                    <TableCell align="right">{t.span_count}</TableCell>
                    <TableCell><CompletionChip status={t.completion_status} missing={t.missing_span_count} /></TableCell>
                    <TableCell><Mono>{t.correlation_id ?? '–'}</Mono></TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </Box>
        )}
        <TablePagination
          component="div"
          count={traces.data?.total ?? 0}
          page={page}
          onPageChange={(_, p) => setPage(p)}
          rowsPerPage={rowsPerPage}
          onRowsPerPageChange={(e) => {
            setRowsPerPage(Number(e.target.value));
            setPage(0);
          }}
          rowsPerPageOptions={[10, 25, 50, 100]}
        />
      </Card>
      <Typography variant="caption" color="text.secondary" sx={{ display: 'block', mt: 1 }}>
        New traces are finalised about 30 s after their last span arrives; the list refreshes every 10 s.
      </Typography>
    </>
  );
}
