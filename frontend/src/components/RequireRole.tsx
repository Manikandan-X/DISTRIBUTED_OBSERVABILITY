import LockIcon from '@mui/icons-material/Lock';
import { Alert, AlertTitle, Box } from '@mui/material';
import type { ReactNode } from 'react';
import { Navigate, useLocation } from 'react-router-dom';
import type { Role } from '../api/types';
import { useAuth } from '../auth/AuthContext';

/** Signed-in users only; optionally requires a minimum role. */
export default function RequireRole({ minimum = 'viewer', children }: { minimum?: Role; children: ReactNode }) {
  const { session, ready, can } = useAuth();
  const location = useLocation();

  if (!ready) return null;
  if (!session) return <Navigate to="/login" replace state={{ from: location.pathname + location.search }} />;
  if (!can(minimum)) {
    return (
      <Box sx={{ maxWidth: 560, mx: 'auto', mt: 6 }}>
        <Alert severity="info" icon={<LockIcon />}>
          <AlertTitle>Access restricted</AlertTitle>
          This page contains log or diagnostic data and requires the <b>{minimum}</b> role. You are signed in as <b>{session.role}</b>.
        </Alert>
      </Box>
    );
  }
  return <>{children}</>;
}
