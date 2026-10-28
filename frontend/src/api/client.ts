import axios, { AxiosError } from 'axios';
import type { ApiErrorBody } from './types';

const TOKEN_KEY = 'obs.token';

export const tokenStore = {
  get: () => sessionStorage.getItem(TOKEN_KEY),
  set: (token: string) => sessionStorage.setItem(TOKEN_KEY, token),
  clear: () => sessionStorage.removeItem(TOKEN_KEY),
};

/** Called when the gateway says the session is no longer valid. */
let onUnauthorized: (() => void) | null = null;
export const setUnauthorizedHandler = (fn: (() => void) | null) => {
  onUnauthorized = fn;
};

export const http = axios.create({
  baseURL: '/api/v1',
  timeout: 15000,
});

http.interceptors.request.use((config) => {
  const token = tokenStore.get();
  if (token) config.headers.Authorization = `Bearer ${token}`;
  return config;
});

http.interceptors.response.use(
  (response) => response,
  (error: AxiosError<ApiErrorBody>) => {
    const isLogin = error.config?.url?.includes('/auth/login');
    if (error.response?.status === 401 && !isLogin) onUnauthorized?.();
    return Promise.reject(error);
  },
);

/** A normalised error the UI can always render. */
export interface UiError {
  status: number | null;
  code: string;
  message: string;
  source: string | null;
  fromGateway: boolean;
  correlationId: string | null;
}

const blank = { source: null, fromGateway: false, correlationId: null };

export function toUiError(err: unknown): UiError {
  if (axios.isAxiosError<ApiErrorBody>(err)) {
    const body = err.response?.data?.error;
    if (body) {
      return {
        status: err.response?.status ?? null,
        code: body.code,
        message: body.message,
        source: body.source,
        fromGateway: err.response?.headers?.['x-error-source'] === 'gateway',
        correlationId: body.correlation_id ?? null,
      };
    }
    if (err.code === 'ECONNABORTED') {
      return { status: null, code: 'timeout', message: 'The request timed out.', ...blank };
    }
    if (!err.response) {
      return { status: null, code: 'network', message: 'Cannot reach the API gateway. Is the backend running?', ...blank };
    }
    return { status: err.response.status, code: 'http_error', message: `Request failed (HTTP ${err.response.status}).`, ...blank };
  }
  return { status: null, code: 'unknown', message: err instanceof Error ? err.message : 'Unexpected error', ...blank };
}
