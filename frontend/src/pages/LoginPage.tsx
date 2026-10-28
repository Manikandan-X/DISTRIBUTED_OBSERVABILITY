import MonitorHeartIcon from '@mui/icons-material/MonitorHeart';
import { Alert, Box, Button, Card, CardContent, Stack, TextField, Typography } from '@mui/material';
import { useState, type FormEvent } from 'react';
import { Navigate, useLocation } from 'react-router-dom';
import { toUiError } from '../api/client';
import { useAuth } from '../auth/AuthContext';

export default function LoginPage() {
  const { session, login } = useAuth();
  const location = useLocation();
  const [username, setUsername] = useState('');
  const [password, setPassword] = useState('');
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  if (session) {
    const from = (location.state as { from?: string } | null)?.from ?? '/';
    return <Navigate to={from} replace />;
  }

  const submit = async (e: FormEvent) => {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      await login(username.trim(), password);
    } catch (err) {
      const ui = toUiError(err);
      setError(ui.code === 'invalid_credentials' ? 'Wrong username or password.' : ui.message);
    } finally {
      setBusy(false);
    }
  };

  return (
    <Box sx={{ minHeight: '100vh', display: 'grid', placeItems: 'center', bgcolor: 'background.default', p: 2 }}>
      <Card sx={{ width: 400, maxWidth: '100%' }}>
        <CardContent sx={{ p: 4 }}>
          <Stack alignItems="center" spacing={1} sx={{ mb: 3 }}>
            <MonitorHeartIcon color="primary" sx={{ fontSize: 44 }} />
            <Typography variant="h5">Observability Console</Typography>
            <Typography variant="body2" color="text.secondary">
              Sign in to view traces, logs, metrics and alerts
            </Typography>
          </Stack>
          <form onSubmit={submit}>
            <Stack spacing={2}>
              {error && <Alert severity="error">{error}</Alert>}
              <TextField label="Username" value={username} onChange={(e) => setUsername(e.target.value)} autoFocus required autoComplete="username" />
              <TextField label="Password" type="password" value={password} onChange={(e) => setPassword(e.target.value)} required autoComplete="current-password" />
              <Button type="submit" variant="contained" size="large" disabled={busy || !username || !password}>
                {busy ? 'Signing in…' : 'Sign in'}
              </Button>
            </Stack>
          </form>
          <Typography variant="caption" color="text.secondary" sx={{ display: 'block', mt: 3 }}>
            Roles: viewer (traces, metrics, alerts) · analyst (+ logs, diagnostics, alert actions) · admin (+ thresholds).
          </Typography>
        </CardContent>
      </Card>
    </Box>
  );
}
