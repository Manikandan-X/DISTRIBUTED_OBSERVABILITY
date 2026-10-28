import { Route, Routes } from 'react-router-dom';
import Layout from './components/Layout';
import RequireRole from './components/RequireRole';
import AlertCenterPage from './pages/AlertCenterPage';
import DependencyMapPage from './pages/DependencyMapPage';
import LoginPage from './pages/LoginPage';
import LogExplorerPage from './pages/LogExplorerPage';
import MetricsPage from './pages/MetricsPage';
import NotFoundPage from './pages/NotFoundPage';
import OverviewPage from './pages/OverviewPage';
import RootCausePage from './pages/RootCausePage';
import TraceDetailPage from './pages/TraceDetailPage';
import TraceExplorerPage from './pages/TraceExplorerPage';

export default function App() {
  return (
    <Routes>
      <Route path="/login" element={<LoginPage />} />
      <Route
        element={
          <RequireRole>
            <Layout />
          </RequireRole>
        }
      >
        <Route index element={<OverviewPage />} />
        <Route path="traces" element={<TraceExplorerPage />} />
        <Route path="traces/:traceId" element={<TraceDetailPage />} />
        <Route path="dependencies" element={<DependencyMapPage />} />
        <Route path="metrics" element={<MetricsPage />} />
        <Route path="alerts" element={<AlertCenterPage />} />
        <Route
          path="logs"
          element={
            <RequireRole minimum="analyst">
              <LogExplorerPage />
            </RequireRole>
          }
        />
        <Route
          path="diagnostics"
          element={
            <RequireRole minimum="analyst">
              <RootCausePage />
            </RequireRole>
          }
        />
        <Route
          path="diagnostics/:reportId"
          element={
            <RequireRole minimum="analyst">
              <RootCausePage />
            </RequireRole>
          }
        />
        <Route path="*" element={<NotFoundPage />} />
      </Route>
    </Routes>
  );
}
