import { Chip, type ChipProps } from '@mui/material';
import type { AlertStatus, RankedService, RootCauseStatus, Severity } from '../api/types';

type Color = ChipProps['color'];

export function SeverityChip({ severity }: { severity: Severity }) {
  const color: Record<Severity, Color> = { INFO: 'info', WARNING: 'warning', ERROR: 'error', CRITICAL: 'error' };
  return (
    <Chip
      size="small"
      label={severity}
      color={color[severity]}
      variant={severity === 'CRITICAL' ? 'filled' : 'outlined'}
      sx={severity === 'CRITICAL' ? { fontWeight: 700 } : undefined}
    />
  );
}

export function TraceStatusChip({ status }: { status: string }) {
  const ok = ['ok', 'success'].includes(status.toLowerCase());
  return <Chip size="small" label={ok ? 'OK' : 'ERROR'} color={ok ? 'success' : 'error'} variant="outlined" />;
}

export function CompletionChip({ status, missing = 0 }: { status: string; missing?: number }) {
  if (status === 'complete') return <Chip size="small" label="complete" color="success" variant="outlined" />;
  if (status === 'incomplete')
    return <Chip size="small" label={`incomplete · ${missing} missing`} color="warning" variant="outlined" />;
  return <Chip size="small" label="in progress" color="info" variant="outlined" />;
}

export function AlertSeverityChip({ severity }: { severity: 'warning' | 'critical' }) {
  return (
    <Chip
      size="small"
      label={severity}
      color={severity === 'critical' ? 'error' : 'warning'}
      sx={{ fontWeight: 600, textTransform: 'uppercase' }}
    />
  );
}

export function AlertStatusChip({ status }: { status: AlertStatus }) {
  const color: Record<AlertStatus, Color> = { active: 'error', acknowledged: 'warning', resolved: 'success' };
  return <Chip size="small" label={status} color={color[status]} variant="outlined" />;
}

export function RootCauseChip({ status }: { status: RootCauseStatus }) {
  const map: Record<RootCauseStatus, { label: string; color: Color }> = {
    confirmed: { label: 'Root cause confirmed', color: 'error' },
    probable: { label: 'Probable cause', color: 'warning' },
    inconclusive: { label: 'Inconclusive', color: 'default' },
    no_issue_detected: { label: 'No issue detected', color: 'success' },
  };
  const { label, color } = map[status];
  return <Chip label={label} color={color} sx={{ fontWeight: 600 }} />;
}

export function ClassificationChip({ value }: { value: RankedService['classification'] }) {
  const map: Record<RankedService['classification'], { label: string; color: Color }> = {
    confirmed: { label: 'confirmed', color: 'error' },
    potential: { label: 'potential', color: 'warning' },
    symptom: { label: 'symptom', color: 'default' },
  };
  return <Chip size="small" label={map[value].label} color={map[value].color} variant="outlined" />;
}
