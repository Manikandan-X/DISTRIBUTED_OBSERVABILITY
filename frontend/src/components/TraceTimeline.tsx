import { Box, Chip, Stack, Tooltip, Typography } from '@mui/material';
import type { Span } from '../api/types';
import { serviceColor } from '../theme';
import { formatMs, parseUtc } from '../utils/format';

interface Props {
  spans: Span[];
  selectedSpanId?: string | null;
  onSelect?: (span: Span) => void;
}

const ROW = 30;
const LABEL_WIDTH = 300;

/**
 * Waterfall: one row per span in execution order, indented by depth.
 * Bars are positioned by start time relative to the whole request.
 *   red    = failed span        orange = slow span
 *   dashed = orphan (its parent span was never received)
 */
export default function TraceTimeline({ spans, selectedSpanId, onSelect }: Props) {
  if (!spans.length) return null;

  const starts = spans.map((s) => parseUtc(s.start_time)?.getTime() ?? 0);
  const ends = spans.map((s, i) => parseUtc(s.end_time)?.getTime() ?? starts[i] + (s.duration_ms ?? 0));
  const t0 = Math.min(...starts);
  const total = Math.max(1, Math.max(...ends) - t0);

  return (
    <Box sx={{ overflowX: 'auto' }}>
      <Stack direction="row" spacing={1} sx={{ mb: 1 }}>
        <Chip size="small" label="failed" sx={{ bgcolor: 'error.main', color: 'white' }} />
        <Chip size="small" label="slow" sx={{ bgcolor: 'warning.main', color: 'white' }} />
        <Chip size="small" label="parent span missing" variant="outlined" sx={{ borderStyle: 'dashed' }} />
        <Typography variant="caption" sx={{ alignSelf: 'center', color: 'text.secondary' }}>
          Total {formatMs(total)}
        </Typography>
      </Stack>

      <Box sx={{ minWidth: 760 }}>
        {spans.map((span, i) => {
          const offset = ((starts[i] - t0) / total) * 100;
          const width = Math.max(0.6, ((ends[i] - starts[i]) / total) * 100);
          const color = span.is_failed ? 'error.main' : span.is_slow ? 'warning.main' : serviceColor(span.service_name);
          const selected = selectedSpanId === span.span_id;
          return (
            <Box
              key={span.span_id}
              onClick={() => onSelect?.(span)}
              sx={{
                display: 'flex',
                alignItems: 'center',
                height: ROW,
                cursor: onSelect ? 'pointer' : 'default',
                bgcolor: selected ? 'action.selected' : 'transparent',
                '&:hover': { bgcolor: 'action.hover' },
                borderBottom: '1px solid',
                borderColor: 'divider',
              }}
            >
              <Box sx={{ width: LABEL_WIDTH, flexShrink: 0, pl: `${span.depth * 14 + 6}px`, pr: 1, overflow: 'hidden', whiteSpace: 'nowrap', textOverflow: 'ellipsis' }}>
                <Box component="span" sx={{ display: 'inline-block', width: 8, height: 8, borderRadius: '50%', bgcolor: serviceColor(span.service_name), mr: 0.75 }} />
                <Typography component="span" variant="body2" sx={{ fontWeight: 600 }}>
                  {span.service_name}
                </Typography>
                <Typography component="span" variant="body2" color="text.secondary">
                  {' · '}
                  {span.operation_name}
                </Typography>
              </Box>
              <Box sx={{ position: 'relative', flexGrow: 1, height: '100%' }}>
                <Tooltip
                  title={`${span.service_name} · ${span.operation_name} — ${formatMs(span.duration_ms)}${span.error_message ? ` — ${span.error_message}` : ''}`}
                >
                  <Box
                    sx={{
                      position: 'absolute',
                      top: 7,
                      height: ROW - 14,
                      left: `${offset}%`,
                      width: `${width}%`,
                      bgcolor: span.is_orphan ? 'transparent' : color,
                      border: span.is_orphan ? '2px dashed' : 'none',
                      borderColor: color,
                      borderRadius: 1,
                      minWidth: 4,
                    }}
                  />
                </Tooltip>
                <Typography
                  variant="caption"
                  sx={{ position: 'absolute', top: 6, left: `calc(${Math.min(offset + width, 88)}% + 6px)`, color: 'text.secondary', whiteSpace: 'nowrap' }}
                >
                  {formatMs(span.duration_ms)}
                </Typography>
              </Box>
            </Box>
          );
        })}
      </Box>
    </Box>
  );
}
