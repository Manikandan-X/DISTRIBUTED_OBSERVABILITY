import { createTheme } from '@mui/material/styles';

export const theme = createTheme({
  palette: {
    mode: 'light',
    primary: { main: '#1f4fd8' },
    secondary: { main: '#6a3fd1' },
    error: { main: '#d32f2f' },
    warning: { main: '#ed8b00' },
    success: { main: '#2e7d32' },
    background: { default: '#f4f6fb' },
  },
  shape: { borderRadius: 10 },
  typography: {
    fontFamily: '"Inter", "Roboto", "Segoe UI", Arial, sans-serif',
    h5: { fontWeight: 700 },
    h6: { fontWeight: 600 },
  },
  components: {
    MuiPaper: { defaultProps: { variant: 'outlined' } },
    MuiCard: { defaultProps: { variant: 'outlined' } },
    MuiTableCell: { styleOverrides: { head: { fontWeight: 600, whiteSpace: 'nowrap' } } },
    MuiButton: { styleOverrides: { root: { textTransform: 'none', fontWeight: 600 } } },
  },
});

/** One colour per service, stable across pages and charts. */
const SERVICE_COLORS = ['#1f4fd8', '#6a3fd1', '#00897b', '#ed8b00', '#c2185b', '#455a64', '#7cb342', '#0288d1'];
export function serviceColor(name: string): string {
  let hash = 0;
  for (const ch of name) hash = (hash * 31 + ch.charCodeAt(0)) >>> 0;
  return SERVICE_COLORS[hash % SERVICE_COLORS.length];
}
