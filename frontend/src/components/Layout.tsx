import AccountTreeIcon from '@mui/icons-material/AccountTree';
import DashboardIcon from '@mui/icons-material/Dashboard';
import LogoutIcon from '@mui/icons-material/Logout';
import MonitorHeartIcon from '@mui/icons-material/MonitorHeart';
import NotificationsActiveIcon from '@mui/icons-material/NotificationsActive';
import QueryStatsIcon from '@mui/icons-material/QueryStats';
import SearchIcon from '@mui/icons-material/Search';
import ShowChartIcon from '@mui/icons-material/ShowChart';
import TroubleshootIcon from '@mui/icons-material/Troubleshoot';
import {
  AppBar,
  Badge,
  Box,
  Chip,
  Divider,
  Drawer,
  IconButton,
  List,
  ListItemButton,
  ListItemIcon,
  ListItemText,
  Toolbar,
  Tooltip,
  Typography,
} from '@mui/material';
import type { ReactNode } from 'react';
import { NavLink, Outlet } from 'react-router-dom';
import { api } from '../api/endpoints';
import type { Role } from '../api/types';
import { useAuth } from '../auth/AuthContext';
import { useAsync } from '../hooks/useAsync';

const WIDTH = 232;

interface NavItem {
  to: string;
  label: string;
  icon: ReactNode;
  minRole: Role;
}

const NAV: NavItem[] = [
  { to: '/', label: 'Overview', icon: <DashboardIcon />, minRole: 'viewer' },
  { to: '/traces', label: 'Trace Explorer', icon: <SearchIcon />, minRole: 'viewer' },
  { to: '/dependencies', label: 'Dependency Map', icon: <AccountTreeIcon />, minRole: 'viewer' },
  { to: '/logs', label: 'Log Explorer', icon: <QueryStatsIcon />, minRole: 'analyst' },
  { to: '/metrics', label: 'Metrics', icon: <ShowChartIcon />, minRole: 'viewer' },
  { to: '/diagnostics', label: 'Root Cause', icon: <TroubleshootIcon />, minRole: 'analyst' },
  { to: '/alerts', label: 'Alert Center', icon: <NotificationsActiveIcon />, minRole: 'viewer' },
];

export default function Layout() {
  const { session, logout, can } = useAuth();
  // Badge with the number of active alerts (refreshes every 30 s).
  const alerts = useAsync(() => api.alerts({ status: 'active', limit: 1 }), [], 30000);
  const active = alerts.data?.total ?? 0;

  return (
    <Box sx={{ display: 'flex' }}>
      <AppBar position="fixed" elevation={0} sx={{ zIndex: (t) => t.zIndex.drawer + 1, borderBottom: 1, borderColor: 'divider' }}>
        <Toolbar>
          <MonitorHeartIcon sx={{ mr: 1.5 }} />
          <Typography variant="h6" sx={{ flexGrow: 1 }}>
            Observability Console
          </Typography>
          {session && (
            <>
              <Chip label={`${session.username} · ${session.role}`} size="small" sx={{ bgcolor: 'rgba(255,255,255,.18)', color: 'inherit', mr: 1 }} />
              <Tooltip title="Sign out">
                <IconButton color="inherit" onClick={logout} aria-label="Sign out">
                  <LogoutIcon />
                </IconButton>
              </Tooltip>
            </>
          )}
        </Toolbar>
      </AppBar>

      <Drawer variant="permanent" sx={{ width: WIDTH, '& .MuiDrawer-paper': { width: WIDTH, boxSizing: 'border-box' } }}>
        <Toolbar />
        <List sx={{ px: 1, pt: 1.5 }}>
          {NAV.map((item) => {
            const allowed = can(item.minRole);
            return (
              <Tooltip key={item.to} title={allowed ? '' : `Requires the ${item.minRole} role`} placement="right">
                <span>
                  <ListItemButton
                    component={NavLink}
                    to={item.to}
                    end={item.to === '/'}
                    disabled={!allowed}
                    sx={{ borderRadius: 2, mb: 0.5, '&.active': { bgcolor: 'primary.main', color: 'primary.contrastText', '& .MuiListItemIcon-root': { color: 'inherit' } } }}
                  >
                    <ListItemIcon sx={{ minWidth: 38 }}>
                      {item.to === '/alerts' && active > 0 ? (
                        <Badge badgeContent={active} color="error" max={99}>
                          {item.icon}
                        </Badge>
                      ) : (
                        item.icon
                      )}
                    </ListItemIcon>
                    <ListItemText primary={item.label} />
                  </ListItemButton>
                </span>
              </Tooltip>
            );
          })}
        </List>
        <Divider sx={{ mt: 'auto' }} />
        <Typography variant="caption" color="text.secondary" sx={{ p: 2 }}>
          Data comes from the live backend. Nothing on these pages is generated in the browser.
        </Typography>
      </Drawer>

      <Box component="main" sx={{ flexGrow: 1, p: 3, minWidth: 0 }}>
        <Toolbar />
        <Outlet />
      </Box>
    </Box>
  );
}
