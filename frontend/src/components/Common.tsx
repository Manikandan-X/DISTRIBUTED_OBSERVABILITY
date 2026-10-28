import { Box, Card, CardContent, Link as MuiLink, MenuItem, Stack, TextField, Typography } from '@mui/material';
import type { ReactNode } from 'react';
import { Link } from 'react-router-dom';
import { shortId, TIME_WINDOWS } from '../utils/format';

export function PageHeader({ title, subtitle, actions }: { title: string; subtitle?: string; actions?: ReactNode }) {
  return (
    <Stack direction={{ xs: 'column', sm: 'row' }} justifyContent="space-between" alignItems={{ sm: 'center' }} spacing={2} sx={{ mb: 2 }}>
      <Box>
        <Typography variant="h5">{title}</Typography>
        {subtitle && (
          <Typography variant="body2" color="text.secondary">
            {subtitle}
          </Typography>
        )}
      </Box>
      <Stack direction="row" spacing={1} alignItems="center" flexWrap="wrap" useFlexGap>
        {actions}
      </Stack>
    </Stack>
  );
}

export function StatCard({
  label,
  value,
  hint,
  tone = 'default',
}: {
  label: string;
  value: ReactNode;
  hint?: string;
  tone?: 'default' | 'error' | 'warning' | 'success';
}) {
  const color = tone === 'default' ? 'text.primary' : `${tone}.main`;
  return (
    <Card sx={{ height: '100%' }}>
      <CardContent>
        <Typography variant="overline" color="text.secondary">
          {label}
        </Typography>
        <Typography variant="h4" sx={{ fontWeight: 700, color }}>
          {value}
        </Typography>
        {hint && (
          <Typography variant="caption" color="text.secondary">
            {hint}
          </Typography>
        )}
      </CardContent>
    </Card>
  );
}

export function TimeWindowSelect({ value, onChange }: { value: number; onChange: (minutes: number) => void }) {
  return (
    <TextField select size="small" label="Time range" value={value} onChange={(e) => onChange(Number(e.target.value))} sx={{ minWidth: 150 }}>
      {TIME_WINDOWS.map((w) => (
        <MenuItem key={w.minutes} value={w.minutes}>
          {w.label}
        </MenuItem>
      ))}
    </TextField>
  );
}

export function TraceLink({ traceId, full = false }: { traceId: string; full?: boolean }) {
  return (
    <MuiLink component={Link} to={`/traces/${traceId}`} underline="hover" sx={{ fontFamily: 'monospace' }} title={traceId}>
      {full ? traceId : shortId(traceId, 12)}
    </MuiLink>
  );
}

export function Mono({ children }: { children: ReactNode }) {
  return <Box component="span" sx={{ fontFamily: 'monospace', fontSize: '0.85em' }}>{children}</Box>;
}
