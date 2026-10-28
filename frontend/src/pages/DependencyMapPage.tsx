import CloseIcon from '@mui/icons-material/Close';
import { Alert, Box, Card, CardContent, Chip, IconButton, Stack, Table, TableBody, TableCell, TableHead, TableRow, Typography } from '@mui/material';
import {
  Background,
  BaseEdge,
  Controls,
  EdgeLabelRenderer,
  getBezierPath,
  Handle,
  MarkerType,
  Position,
  ReactFlow,
  type Edge,
  type EdgeProps,
  type Node,
  type NodeProps,
} from '@xyflow/react';
import '@xyflow/react/dist/style.css';
import { useMemo, useState } from 'react';
import { useSearchParams } from 'react-router-dom';
import { api } from '../api/endpoints';
import type { DependencyEdgeData, DependencyGraph, DependencyNodeData } from '../api/types';
import { EmptyState, ErrorAlert, LoadingBar } from '../components/AsyncState';
import { PageHeader, TimeWindowSelect } from '../components/Common';
import { useAsync } from '../hooks/useAsync';
import { formatDateTime, formatMs, formatNumber, formatPercent, minutesAgoIso } from '../utils/format';

type ServiceNodeData = { info: DependencyNodeData; highlighted: boolean };
type ServiceFlowNode = Node<ServiceNodeData, 'service'>;
type CallEdgeData = { edge: DependencyEdgeData };
type CallFlowEdge = Edge<CallEdgeData, 'call'>;

const errorColor = (rate: number) => (rate >= 20 ? '#d32f2f' : rate > 0 ? '#ed8b00' : '#2e7d32');

function ServiceNode({ data }: NodeProps<ServiceFlowNode>) {
  const { info, highlighted } = data;
  const color = errorColor(info.error_rate_percent);
  return (
    <Box
      sx={{
        width: 210,
        bgcolor: 'background.paper',
        border: '2px solid',
        borderColor: highlighted ? 'primary.main' : color,
        borderRadius: 2,
        boxShadow: highlighted ? 6 : 1,
        p: 1.25,
      }}
    >
      <Handle type="target" position={Position.Left} />
      <Typography sx={{ fontWeight: 700 }} noWrap title={info.service_name}>
        {info.service_name}
      </Typography>
      <Stack direction="row" justifyContent="space-between" sx={{ mt: 0.5 }}>
        <Typography variant="caption" color="text.secondary">
          {formatNumber(info.request_count)} req
        </Typography>
        <Typography variant="caption" sx={{ color, fontWeight: 700 }}>
          {formatPercent(info.error_rate_percent)} err
        </Typography>
        <Typography variant="caption" color="text.secondary">
          {formatMs(info.average_duration_ms)}
        </Typography>
      </Stack>
      <Handle type="source" position={Position.Right} />
    </Box>
  );
}

function CallEdge({ id, sourceX, sourceY, targetX, targetY, sourcePosition, targetPosition, data, markerEnd }: EdgeProps<CallFlowEdge>) {
  const [path, labelX, labelY] = getBezierPath({ sourceX, sourceY, targetX, targetY, sourcePosition, targetPosition });
  const edge = data?.edge;
  const failed = !!edge?.observed_failure;
  return (
    <>
      <BaseEdge id={id} path={path} markerEnd={markerEnd} style={{ stroke: failed ? '#d32f2f' : '#90a4ae', strokeWidth: failed ? 2.5 : 1.8 }} />
      {edge && (
        <EdgeLabelRenderer>
          <Box
            sx={{
              position: 'absolute',
              transform: `translate(-50%, -50%) translate(${labelX}px, ${labelY}px)`,
              bgcolor: failed ? '#fdecea' : 'background.paper',
              border: '1px solid',
              borderColor: failed ? 'error.main' : 'divider',
              borderRadius: 1,
              px: 0.75,
              py: 0.25,
              fontSize: 11,
              pointerEvents: 'all',
              whiteSpace: 'nowrap',
            }}
          >
            {edge.request_count} calls · {formatMs(edge.average_duration_ms)}
            {failed && <b style={{ color: '#d32f2f' }}> · {edge.error_count} failed</b>}
          </Box>
        </EdgeLabelRenderer>
      )}
    </>
  );
}

const nodeTypes = { service: ServiceNode };
const edgeTypes = { call: CallEdge };

/** Layered left-to-right layout (longest path from the entry services). */
function layout(graph: DependencyGraph, selected: string | null): { nodes: ServiceFlowNode[]; edges: CallFlowEdge[] } {
  const names = graph.nodes.map((n) => n.service_name);
  const incoming = new Map<string, string[]>(names.map((n) => [n, []]));
  graph.edges.forEach((e) => incoming.get(e.target)?.push(e.source));

  const layer = new Map<string, number>();
  const visit = (name: string, trail: Set<string>): number => {
    if (layer.has(name)) return layer.get(name)!;
    if (trail.has(name)) return 0; // cycle guard
    trail.add(name);
    const parents = incoming.get(name) ?? [];
    const value = parents.length ? Math.max(...parents.map((p) => visit(p, trail))) + 1 : 0;
    trail.delete(name);
    layer.set(name, value);
    return value;
  };
  names.forEach((n) => visit(n, new Set()));

  const rows = new Map<number, number>();
  const nodes: ServiceFlowNode[] = graph.nodes.map((info) => {
    const col = layer.get(info.service_name) ?? 0;
    const row = rows.get(col) ?? 0;
    rows.set(col, row + 1);
    return {
      id: info.service_name,
      type: 'service',
      position: { x: col * 340, y: row * 130 },
      data: { info, highlighted: info.service_name === selected },
    };
  });

  const edges: CallFlowEdge[] = graph.edges.map((e) => ({
    id: `${e.source}->${e.target}`,
    source: e.source,
    target: e.target,
    type: 'call',
    animated: e.observed_failure,
    markerEnd: { type: MarkerType.ArrowClosed, color: e.observed_failure ? '#d32f2f' : '#90a4ae' },
    data: { edge: e },
  }));
  return { nodes, edges };
}

export default function DependencyMapPage() {
  const [params, setParams] = useSearchParams();
  const selected = params.get('service');
  const [minutes, setMinutes] = useState(60);

  const since = useMemo(() => minutesAgoIso(minutes), [minutes]);
  const graph = useAsync(() => api.dependencies(since), [since], 15000);
  const details = useAsync(() => api.serviceDependencies(selected!, since), [selected, since], 15000, !!selected);

  const flow = useMemo(() => (graph.data ? layout(graph.data, selected) : { nodes: [], edges: [] }), [graph.data, selected]);
  const select = (name: string | null) => {
    const next = new URLSearchParams(params);
    if (name) next.set('service', name);
    else next.delete('service');
    setParams(next, { replace: true });
  };

  return (
    <>
      <PageHeader
        title="Service Dependency Map"
        subtitle="Derived from observed parent/child spans: nothing here is hard-coded"
        actions={<TimeWindowSelect value={minutes} onChange={setMinutes} />}
      />
      <LoadingBar loading={graph.loading && !graph.data} />
      {graph.error && <ErrorAlert error={graph.error} onRetry={graph.reload} />}

      <Stack direction={{ xs: 'column', lg: 'row' }} spacing={2} alignItems="stretch">
        <Card sx={{ flexGrow: 1, minWidth: 0 }}>
          <Box sx={{ height: 560 }}>
            {graph.data && graph.data.nodes.length === 0 ? (
              <EmptyState>No service interactions were observed in this window. Send a sample request to see the graph.</EmptyState>
            ) : (
              <ReactFlow
                nodes={flow.nodes}
                edges={flow.edges}
                nodeTypes={nodeTypes}
                edgeTypes={edgeTypes}
                onNodeClick={(_, node) => select(node.id)}
                onPaneClick={() => select(null)}
                fitView
                fitViewOptions={{ padding: 0.25 }}
                nodesConnectable={false}
                proOptions={{ hideAttribution: true }}
              >
                <Background />
                <Controls showInteractive={false} />
              </ReactFlow>
            )}
          </Box>
          <CardContent sx={{ py: 1 }}>
            <Stack direction="row" spacing={2} flexWrap="wrap" useFlexGap>
              <Legend color="#2e7d32" label="no errors" />
              <Legend color="#ed8b00" label="some errors" />
              <Legend color="#d32f2f" label="error rate ≥ 20% / failing call" />
              <Typography variant="caption" color="text.secondary">
                Click a service to inspect its incoming and outgoing dependencies.
              </Typography>
            </Stack>
          </CardContent>
        </Card>

        {selected && (
          <Card sx={{ width: { lg: 440 }, flexShrink: 0 }}>
            <CardContent>
              <Stack direction="row" justifyContent="space-between" alignItems="center">
                <Typography variant="h6">{selected}</Typography>
                <IconButton onClick={() => select(null)} aria-label="Close panel">
                  <CloseIcon />
                </IconButton>
              </Stack>
              <LoadingBar loading={details.loading && !details.data} />
              {details.error && <ErrorAlert error={details.error} onRetry={details.reload} />}
              {details.data && (
                <>
                  <Stack direction="row" spacing={1} sx={{ my: 1 }} flexWrap="wrap" useFlexGap>
                    <Chip size="small" label={`${formatNumber(details.data.service.request_count)} requests`} />
                    <Chip size="small" color={details.data.service.error_rate_percent > 0 ? 'error' : 'success'} variant="outlined" label={`${formatPercent(details.data.service.error_rate_percent)} errors`} />
                    <Chip size="small" label={`avg ${formatMs(details.data.service.average_duration_ms)}`} />
                  </Stack>
                  <EdgeTable title="Called by (incoming)" edges={details.data.incoming} other="source" />
                  <EdgeTable title="Calls (outgoing)" edges={details.data.outgoing} other="target" />
                </>
              )}
            </CardContent>
          </Card>
        )}
      </Stack>

      {graph.data && graph.data.failure_relationships.length > 0 && (
        <Alert severity="error" sx={{ mt: 2 }}>
          <b>Observed failure relationships:</b>
          <ul style={{ margin: '4px 0 0', paddingLeft: 18 }}>
            {graph.data.failure_relationships.map((f) => (
              <li key={`${f.source}-${f.target}`}>
                {f.source} → {f.target}: {f.failed_calls} failed call(s), last at {formatDateTime(f.last_error_at)}
              </li>
            ))}
          </ul>
        </Alert>
      )}
    </>
  );
}

function Legend({ color, label }: { color: string; label: string }) {
  return (
    <Stack direction="row" spacing={0.75} alignItems="center">
      <Box sx={{ width: 12, height: 12, borderRadius: '3px', bgcolor: color }} />
      <Typography variant="caption">{label}</Typography>
    </Stack>
  );
}

function EdgeTable({ title, edges, other }: { title: string; edges: DependencyEdgeData[]; other: 'source' | 'target' }) {
  return (
    <>
      <Typography variant="subtitle2" sx={{ mt: 2 }}>
        {title}
      </Typography>
      {edges.length === 0 ? (
        <Typography variant="body2" color="text.secondary">
          None observed.
        </Typography>
      ) : (
        <Table size="small">
          <TableHead>
            <TableRow>
              <TableCell>Service</TableCell>
              <TableCell align="right">Calls</TableCell>
              <TableCell align="right">Errors</TableCell>
              <TableCell align="right">Avg</TableCell>
            </TableRow>
          </TableHead>
          <TableBody>
            {edges.map((e) => (
              <TableRow key={`${e.source}-${e.target}`}>
                <TableCell>{e[other]}</TableCell>
                <TableCell align="right">{e.request_count}</TableCell>
                <TableCell align="right" sx={{ color: e.error_count ? 'error.main' : undefined }}>
                  {e.error_count} ({formatPercent(e.error_rate_percent, 0)})
                </TableCell>
                <TableCell align="right">{formatMs(e.average_duration_ms)}</TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      )}
    </>
  );
}
