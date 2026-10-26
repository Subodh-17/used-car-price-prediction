// @ts-check
/**
 * Centralised API client. Every dashboard component and the estimator use this module; there is no mock data.
 *
 * @typedef {{ make: string, model: string, variant?: string|null, year: number, km_driven: number, fuel: string, transmission: string,
 *   owner_count?: number|null, body_type?: string|null, engine_cc?: number|null, max_power_bhp?: number|null, mileage?: number|null,
 *   seats?: number|null, city?: string|null, seller_type?: string|null }} PredictRequest
 * @typedef {{ low_inr: number, high_inr: number, nominal_coverage: number, empirical_test_coverage: number, method: string }} Interval
 * @typedef {{ factor: string, effect_inr: number }} Effect
 * @typedef {{ estimated_price_inr: number, interval: Interval|null, interval_note: string|null,
 *   warnings: {code: string, message: string}[], defaults_applied: object[], inputs_used: Record<string, any>,
 *   explanation: {method: string, effects: Effect[], note: string}|null,
 *   model: {estimator: string, data_version: string, trained_utc: string, valuation_year: number}, disclaimer: string,
 *   saved_to_history: boolean }} PredictResponse
 */
import { apiBase } from './config.js';

export class ApiError extends Error {
  /** @param {string} code @param {string} message @param {number} status @param {any} [details] */
  constructor(code, message, status, details = {}) {
    super(message);
    this.name = 'ApiError';
    this.code = code;
    this.status = status;
    this.details = details;
  }
  /** Service failures can be retried; unsupported vehicles / validation errors cannot. */
  get retryable() { return ['network_error', 'timeout', 'model_unavailable', 'internal_error'].includes(this.code) || this.status === 503 || this.status === 504; }
  get kind() {
    if (this.retryable) return 'service';
    if (['unsupported_vehicle', 'year_out_of_coverage', 'unsupported_value'].includes(this.code)) return 'unsupported';
    return 'validation';
  }
}

const TIMEOUT_MS = 15000;
const cache = new Map();

/** @param {string} path @param {{method?: string, body?: any, headers?: Record<string,string>, signal?: AbortSignal, fetchImpl?: typeof fetch}} [opts] */
export async function request(path, opts = {}) {
  const { method = 'GET', body, headers = {}, signal, fetchImpl = globalThis.fetch } = opts;
  const ctrl = new AbortController();
  const timer = setTimeout(() => ctrl.abort(new DOMException('timeout', 'TimeoutError')), TIMEOUT_MS);
  signal?.addEventListener('abort', () => ctrl.abort(signal.reason), { once: true });
  let res;
  try {
    res = await fetchImpl(`${apiBase()}${path}`, {
      method, signal: ctrl.signal,
      headers: { Accept: 'application/json', ...(body ? { 'Content-Type': 'application/json' } : {}), ...headers },
      body: body ? JSON.stringify(body) : undefined,
    });
  } catch (err) {
    if (signal?.aborted) throw err;                                   // caller cancelled: not an error to display
    const timedOut = err && (err.name === 'TimeoutError' || ctrl.signal.aborted);
    throw new ApiError(timedOut ? 'timeout' : 'network_error', timedOut ? 'The server took too long to respond.' : 'Cannot reach the prediction service.', 0);
  } finally {
    clearTimeout(timer);
  }
  let data = null;
  try { data = await res.json(); } catch { /* non-JSON body */ }
  if (!res.ok) {
    const e = data?.error;
    throw new ApiError(e?.code ?? (res.status >= 500 ? 'internal_error' : 'request_failed'), e?.message ?? `Request failed (${res.status}).`, res.status, e?.details ?? {});
  }
  if (data === null) throw new ApiError('bad_response', 'The server returned an unreadable response.', res.status);
  return data;
}

/** GET with up to `retries` retries (exponential back-off) for retryable failures only. */
export async function getWithRetry(path, { retries = 2, delayMs = 400, ...opts } = {}) {
  for (let attempt = 0; ; attempt++) {
    try { return await request(path, opts); }
    catch (err) {
      if (!(err instanceof ApiError) || !err.retryable || attempt >= retries) throw err;
      await new Promise((r) => setTimeout(r, delayMs * 2 ** attempt));
    }
  }
}

const cached = (key, fn) => {
  if (!cache.has(key)) cache.set(key, fn().catch((e) => { cache.delete(key); throw e; }));
  return cache.get(key);
};
export const clearCache = () => cache.clear();

export const api = {
  health: () => request('/api/health'),
  metadata: () => cached('metadata', () => getWithRetry('/api/metadata')),
  modelMetrics: () => cached('metrics', () => getWithRetry('/api/model-metrics')),
  analytics: () => cached('analytics', () => getWithRetry('/api/analytics')),
  vehicleOptions: () => cached('options', () => getWithRetry('/api/vehicle-options')),
  models: (make) => cached(`models:${make}`, () => getWithRetry(`/api/vehicle-options?make=${encodeURIComponent(make)}`)),
  modelDetail: (make, model) => cached(`model:${make}|${model}`, () => getWithRetry(`/api/vehicle-options?make=${encodeURIComponent(make)}&model=${encodeURIComponent(model)}`)),
  /** @param {PredictRequest} payload @param {{clientId?: string|null, signal?: AbortSignal}} [o] @returns {Promise<PredictResponse>} */
  predict: (payload, { clientId = null, signal } = {}) => request('/api/predict', { method: 'POST', body: payload, signal, headers: clientId ? { 'X-Client-Id': clientId } : {} }),
  history: (clientId) => request('/api/history', { headers: { 'X-Client-Id': clientId } }),
  clearHistory: (clientId) => request('/api/history', { method: 'DELETE', headers: { 'X-Client-Id': clientId } }),
};

/** Random per-browser id used only to keep prediction history private to this browser. */
export function getClientId(storage = globalThis.localStorage) {
  try {
    let id = storage.getItem('ucp_client_id');
    if (!id) { id = globalThis.crypto.randomUUID(); storage.setItem('ucp_client_id', id); }
    return id;
  } catch { return null; }
}
