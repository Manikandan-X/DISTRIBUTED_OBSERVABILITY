import RefreshIcon from '@mui/icons-material/Refresh';
import { Alert, AlertTitle, Box, Button, LinearProgress, Stack, Typography } from '@mui/material';
import type { ReactNode } from 'react';
import type { UiError } from '../api/client';

export function LoadingBar({ loading }: { loading: boolean }) {
  return <Box sx={{ height: 4 }}>{loading && <LinearProgress />}</Box>;
}

/** Shows what failed and WHO failed (gateway vs a downstream service). */
export function ErrorAlert({ error, onRetry }: { error: UiError; onRetry?: () => void }) {
  const forbidden = error.status === 403;
  return (
    <Alert
      severity={forbidden ? 'info' : 'error'}
      sx={{ mb: 2 }}
      action={
        onRetry && !forbidden ? (
          <Button color="inherit" size="small" startIcon={<RefreshIcon />} onClick={onRetry}>
            Retry
          </Button>
        ) : undefined
      }
    >
      <AlertTitle>{forbidden ? 'Not allowed for your role' : titleFor(error)}</AlertTitle>
      {error.message}
      {error.correlationId && (
        <Typography variant="caption" display="block" sx={{ opacity: 0.8, mt: 0.5 }}>
          Correlation ID: {error.correlationId}
        </Typography>
      )}
    </Alert>
  );
}

function titleFor(error: UiError): string {
  if (error.code === 'network') return 'Backend unreachable';
  if (error.code === 'downstream_timeout') return `${error.source ?? 'A service'} timed out`;
  if (error.code === 'downstream_unavailable') return `${error.source ?? 'A service'} is unavailable`;
  if (error.fromGateway) return 'Rejected by the API gateway';
  if (error.source) return `Error from ${error.source}`;
  return 'Something went wrong';
}

/** Warnings attached to partial results (a service was down, data hidden...). */
export function PartialWarnings({ warnings, partial }: { warnings?: string[]; partial?: boolean }) {
  if (!warnings?.length && !partial) return null;
  return (
    <Alert severity="warning" sx={{ mb: 2 }}>
      <AlertTitle>{partial ? 'Partial result' : 'Notes'}</AlertTitle>
      <Stack component="ul" sx={{ m: 0, pl: 2 }}>
        {warnings?.map((w) => (
          <li key={w}>{w}</li>
        ))}
      </Stack>
    </Alert>
  );
}

export function EmptyState({ children }: { children: ReactNode }) {
  return (
    <Box sx={{ py: 5, textAlign: 'center', color: 'text.secondary' }}>
      <Typography>{children}</Typography>
    </Box>
  );
}
