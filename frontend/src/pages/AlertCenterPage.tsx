import ExpandMoreIcon from '@mui/icons-material/ExpandMore';
import {
  Alert as MuiAlert,
  Box,
  Button,
  Card,
  CardContent,
  Collapse,
  FormControlLabel,
  IconButton,
  MenuItem,
  Stack,
  Switch,
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
import { useState } from 'react';
import { Link } from 'react-router-dom';
import { toUiError } from '../api/client';
import { api } from '../api/endpoints';
import type { Alert, AlertStatus } from '../api/types';
import { useAuth } from '../auth/AuthContext';
import { AlertSeverityChip, AlertStatusChip } from '../components/Chips';
import { EmptyState, ErrorAlert, LoadingBar } from '../components/AsyncState';
import { PageHeader, TraceLink } from '../components/Common';
import { useAsync } from '../hooks/useAsync';
import { ALERT_TYPE_LABELS, formatAlertValue, formatDateTime } from '../utils/format';

const TABS: { label: string; status?: AlertStatus }[] = [
  { label: 'Active', status: 'active' },
  { label: 'Acknowledged', status: 'acknowledged' },
  { label: 'Resolved', status: 'resolved' },
  { label: 'All' },
  { label: 'Thresholds' },
];

export default function AlertCenterPage() {
  const { can } = useAuth();
  const [tab, setTab] = useState(0);
  const [page, setPage] = useState(0);
  const [rowsPerPage, setRowsPerPage] = useState(25);
  const [auto, setAuto] = useState(true);
  const [actionError, setActionError] = useState<string | null>(null);
  const isRules = tab === TABS.length - 1;

  const alerts = useAsync(
    () => api.alerts({ status: TABS[tab].status, limit: rowsPerPage, offset: page * rowsPerPage }),
    [tab, page, rowsPerPage],
    auto ? 15000 : 0,
    !isRules,
  );

  const act = async (alert: Alert, status: 'acknowledged' | 'resolved') => {
    setActionError(null);
    try {
      await api.updateAlert(alert.id, status);
      await alerts.reload();
    } catch (err) {
      setActionError(toUiError(err).message);
    }
  };

  return (
    <>
      <PageHeader
        title="Alert Center"
        subtitle="Threshold violations with the evidence behind them"
        actions={<FormControlLabel control={<Switch checked={auto} onChange={(e) => setAuto(e.target.checked)} />} label="Auto-refresh" />}
      />
      <Card>
        <Tabs
          value={tab}
          onChange={(_, v: number) => {
            setTab(v);
            setPage(0);
          }}
          sx={{ borderBottom: 1, borderColor: 'divider', px: 2 }}
        >
          {TABS.map((t) => (
            <Tab key={t.label} label={t.label} />
          ))}
        </Tabs>

        {!isRules && (
          <>
            <LoadingBar loading={alerts.loading && !alerts.data} />
            {alerts.error && <Box sx={{ p: 2 }}><ErrorAlert error={alerts.error} onRetry={alerts.reload} /></Box>}
            {actionError && <MuiAlert severity="error" sx={{ m: 2 }}>{actionError}</MuiAlert>}
            {alerts.data && alerts.data.items.length === 0 && <EmptyState>No alerts here.</EmptyState>}
            {!!alerts.data?.items.length && (
              <Box sx={{ overflowX: 'auto' }}>
                <Table size="small">
                  <TableHead>
                    <TableRow>
                      <TableCell />
                      <TableCell>Severity</TableCell>
                      <TableCell>Service</TableCell>
                      <TableCell>Violation</TableCell>
                      <TableCell>Status</TableCell>
                      <TableCell align="right">Seen</TableCell>
                      <TableCell>Last seen</TableCell>
                      <TableCell>Actions</TableCell>
                    </TableRow>
                  </TableHead>
                  <TableBody>
                    {alerts.data.items.map((a) => (
                      <AlertRow key={a.id} alert={a} canAct={can('analyst')} onAct={act} />
                    ))}
                  </TableBody>
                </Table>
              </Box>
            )}
            <TablePagination
              component="div"
              count={alerts.data?.total ?? 0}
              page={page}
              onPageChange={(_, p) => setPage(p)}
              rowsPerPage={rowsPerPage}
              onRowsPerPageChange={(e) => {
                setRowsPerPage(Number(e.target.value));
                setPage(0);
              }}
              rowsPerPageOptions={[10, 25, 50]}
            />
            {!can('analyst') && (
              <Typography variant="caption" color="text.secondary" sx={{ display: 'block', p: 2 }}>
                Acknowledging or resolving alerts requires the analyst role.
              </Typography>
            )}
          </>
        )}

        {isRules && <RulesPanel canEdit={can('admin')} />}
      </Card>
    </>
  );
}

function AlertRow({ alert, canAct, onAct }: { alert: Alert; canAct: boolean; onAct: (a: Alert, s: 'acknowledged' | 'resolved') => void }) {
  const [open, setOpen] = useState(false);
  const [busy, setBusy] = useState(false);
  const run = async (s: 'acknowledged' | 'resolved') => {
    setBusy(true);
    await onAct(alert, s);
    setBusy(false);
  };
  const ratio = alert.threshold_value > 0 ? alert.measured_value / alert.threshold_value : 0;

  return (
    <>
      <TableRow hover>
        <TableCell sx={{ width: 40, p: 0.5 }}>
          <IconButton size="small" onClick={() => setOpen(!open)} aria-label="Show evidence" sx={{ transform: open ? 'rotate(180deg)' : 'none', transition: '150ms' }}>
            <ExpandMoreIcon fontSize="small" />
          </IconButton>
        </TableCell>
        <TableCell><AlertSeverityChip severity={alert.severity} /></TableCell>
        <TableCell sx={{ fontWeight: 600 }}>{alert.service_name}</TableCell>
        <TableCell>
          {ALERT_TYPE_LABELS[alert.alert_type] ?? alert.alert_type}:{' '}
          <b>{formatAlertValue(alert.alert_type, alert.measured_value)}</b> (limit {formatAlertValue(alert.alert_type, alert.threshold_value)}, {ratio.toFixed(1)}×)
        </TableCell>
        <TableCell><AlertStatusChip status={alert.status} /></TableCell>
        <TableCell align="right">{alert.occurrence_count}×</TableCell>
        <TableCell sx={{ whiteSpace: 'nowrap' }}>{formatDateTime(alert.last_seen_at)}</TableCell>
        <TableCell sx={{ whiteSpace: 'nowrap' }}>
          {canAct && alert.status === 'active' && (
            <Button size="small" disabled={busy} onClick={() => run('acknowledged')}>
              Acknowledge
            </Button>
          )}
          {canAct && alert.status !== 'resolved' && (
            <Button size="small" color="success" disabled={busy} onClick={() => run('resolved')}>
              Resolve
            </Button>
          )}
        </TableCell>
      </TableRow>
      <TableRow>
        <TableCell colSpan={8} sx={{ p: 0, border: open ? undefined : 0 }}>
          <Collapse in={open} unmountOnExit>
            <Box sx={{ p: 2, bgcolor: 'action.hover' }}>
              <Typography variant="subtitle2">Evidence</Typography>
              <Typography variant="body2">First seen: {formatDateTime(alert.first_seen_at)}</Typography>
              <Typography variant="body2">Last seen: {formatDateTime(alert.last_seen_at)}</Typography>
              {alert.acknowledged_at && <Typography variant="body2">Acknowledged: {formatDateTime(alert.acknowledged_at)}</Typography>}
              {alert.resolved_at && <Typography variant="body2">Resolved: {formatDateTime(alert.resolved_at)}</Typography>}
              <Typography variant="body2" sx={{ mt: 1 }}>Related traces:</Typography>
              {alert.trace_ids.length === 0 ? (
                <Typography variant="body2" color="text.secondary">None were attached (samples carried no trace ID).</Typography>
              ) : (
                <Stack>
                  {alert.trace_ids.map((t) => (
                    <Stack key={t} direction="row" spacing={2}>
                      <TraceLink traceId={t} full />
                      {canAct && <Link to={`/diagnostics?trace=${t}`}>Analyse</Link>}
                    </Stack>
                  ))}
                </Stack>
              )}
            </Box>
          </Collapse>
        </TableCell>
      </TableRow>
    </>
  );
}

const RULE_TYPES = Object.keys(ALERT_TYPE_LABELS);

function RulesPanel({ canEdit }: { canEdit: boolean }) {
  const rules = useAsync(() => api.alertRules(), []);
  const [type, setType] = useState(RULE_TYPES[0]);
  const [service, setService] = useState('*');
  const [value, setValue] = useState('');
  const [enabled, setEnabled] = useState(true);
  const [message, setMessage] = useState<{ ok: boolean; text: string } | null>(null);

  const save = async () => {
    setMessage(null);
    try {
      await api.saveAlertRule({ alert_type: type, service_name: service.trim() || '*', threshold_value: Number(value), enabled });
      setMessage({ ok: true, text: 'Threshold saved. It applies from the next evaluation (within 30 s).' });
      await rules.reload();
    } catch (err) {
      setMessage({ ok: false, text: toUiError(err).message });
    }
  };

  return (
    <CardContent>
      <LoadingBar loading={rules.loading && !rules.data} />
      {rules.error && <ErrorAlert error={rules.error} onRetry={rules.reload} />}
      {rules.data && (
        <>
          <Typography variant="h6">Default thresholds</Typography>
          <Typography variant="caption" color="text.secondary">
            From the backend environment. An alert fires when the latest one-minute bucket exceeds the value.
          </Typography>
          <Table size="small" sx={{ mb: 3 }}>
            <TableBody>
              {rules.data.defaults.map((r) => (
                <TableRow key={r.alert_type}>
                  <TableCell>{ALERT_TYPE_LABELS[r.alert_type] ?? r.alert_type}</TableCell>
                  <TableCell align="right">{formatAlertValue(r.alert_type, r.threshold_value)}</TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>

          <Typography variant="h6">Overrides</Typography>
          {rules.data.overrides.length === 0 ? (
            <Typography variant="body2" color="text.secondary" sx={{ mb: 2 }}>
              No overrides configured.
            </Typography>
          ) : (
            <Table size="small" sx={{ mb: 3 }}>
              <TableHead>
                <TableRow>
                  <TableCell>Type</TableCell>
                  <TableCell>Service</TableCell>
                  <TableCell align="right">Threshold</TableCell>
                  <TableCell>Enabled</TableCell>
                </TableRow>
              </TableHead>
              <TableBody>
                {rules.data.overrides.map((r) => (
                  <TableRow key={`${r.alert_type}-${r.service_name}`}>
                    <TableCell>{ALERT_TYPE_LABELS[r.alert_type] ?? r.alert_type}</TableCell>
                    <TableCell>{r.service_name === '*' ? 'all services' : r.service_name}</TableCell>
                    <TableCell align="right">{formatAlertValue(r.alert_type, r.threshold_value)}</TableCell>
                    <TableCell>{r.enabled ? 'yes' : 'no'}</TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          )}

          {canEdit ? (
            <>
              <Typography variant="h6" gutterBottom>
                Change a threshold
              </Typography>
              <Stack direction={{ xs: 'column', md: 'row' }} spacing={2} alignItems={{ md: 'center' }}>
                <TextField select size="small" label="Alert type" value={type} onChange={(e) => setType(e.target.value)} sx={{ minWidth: 190 }}>
                  {RULE_TYPES.map((t) => (
                    <MenuItem key={t} value={t}>
                      {ALERT_TYPE_LABELS[t]}
                    </MenuItem>
                  ))}
                </TextField>
                <TextField size="small" label="Service (* = all)" value={service} onChange={(e) => setService(e.target.value)} />
                <TextField size="small" label={type === 'error_rate_percent' ? 'Threshold (%)' : type === 'request_volume' ? 'Threshold (requests/min)' : 'Threshold (ms)'} type="number" value={value} onChange={(e) => setValue(e.target.value)} />
                <FormControlLabel control={<Switch checked={enabled} onChange={(e) => setEnabled(e.target.checked)} />} label="Enabled" />
                <Button variant="contained" onClick={save} disabled={value === '' || Number(value) < 0}>
                  Save
                </Button>
              </Stack>
              {message && <MuiAlert severity={message.ok ? 'success' : 'error'} sx={{ mt: 2 }}>{message.text}</MuiAlert>}
            </>
          ) : (
            <Typography variant="caption" color="text.secondary">
              Changing thresholds requires the admin role.
            </Typography>
          )}
        </>
      )}
    </CardContent>
  );
}
