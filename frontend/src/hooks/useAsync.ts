import { useCallback, useEffect, useRef, useState } from 'react';
import { toUiError, type UiError } from '../api/client';

interface State<T> {
  data: T | null;
  error: UiError | null;
  loading: boolean;
}

/**
 * Runs an async loader whenever `deps` change and optionally every `pollMs`.
 * Keeps the previous data on screen while refreshing (no flicker) and ignores
 * responses from stale requests.
 */
export function useAsync<T>(loader: () => Promise<T>, deps: unknown[], pollMs = 0, enabled = true) {
  const [state, setState] = useState<State<T>>({ data: null, error: null, loading: enabled });
  const requestId = useRef(0);
  const loaderRef = useRef(loader);
  loaderRef.current = loader;

  const run = useCallback(async () => {
    const id = ++requestId.current;
    setState((s) => ({ ...s, loading: true }));
    try {
      const data = await loaderRef.current();
      if (id === requestId.current) setState({ data, error: null, loading: false });
    } catch (err) {
      if (id === requestId.current) setState((s) => ({ data: s.data, error: toUiError(err), loading: false }));
    }
  }, []);

  useEffect(() => {
    if (!enabled) {
      setState({ data: null, error: null, loading: false });
      return;
    }
    void run();
    if (!pollMs) return;
    const timer = window.setInterval(() => void run(), pollMs);
    return () => window.clearInterval(timer);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [...deps, pollMs, enabled]);

  return { ...state, reload: run };
}
