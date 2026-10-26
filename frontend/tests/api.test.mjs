import test from 'node:test';
import assert from 'node:assert/strict';
import { request, getWithRetry, ApiError, api, getClientId, clearCache } from '../js/api.js';

const json = (status, body) => ({ ok: status < 400, status, json: async () => body });

test('successful JSON response is returned', async () => {
  const data = await request('/api/health', { fetchImpl: async () => json(200, { status: 'ok' }) });
  assert.deepEqual(data, { status: 'ok' });
});
test('server error envelope is mapped to ApiError with code, status and details', async () => {
  const f = async () => json(422, { error: { code: 'unsupported_vehicle', message: 'nope', details: { field: 'model' } } });
  await assert.rejects(request('/api/predict', { method: 'POST', body: {}, fetchImpl: f }), (e) => {
    assert.ok(e instanceof ApiError);
    assert.equal(e.code, 'unsupported_vehicle'); assert.equal(e.status, 422); assert.equal(e.kind, 'unsupported'); assert.equal(e.retryable, false);
    assert.equal(e.details.field, 'model');
    return true;
  });
});
test('503 is a retryable service failure, network failure is distinguished', async () => {
  const e503 = await request('/x', { fetchImpl: async () => json(503, { error: { code: 'model_unavailable', message: 'down' } }) }).catch((e) => e);
  assert.equal(e503.kind, 'service'); assert.equal(e503.retryable, true);
  const net = await request('/x', { fetchImpl: async () => { throw new TypeError('fetch failed'); } }).catch((e) => e);
  assert.equal(net.code, 'network_error'); assert.equal(net.kind, 'service');
});
test('non-JSON error body still yields a safe ApiError', async () => {
  const f = async () => ({ ok: false, status: 502, json: async () => { throw new Error('bad'); } });
  const e = await request('/x', { fetchImpl: f }).catch((x) => x);
  assert.equal(e.code, 'internal_error');
});
test('getWithRetry retries retryable errors only', async () => {
  let calls = 0;
  const flaky = async () => (++calls < 3 ? json(503, { error: { code: 'model_unavailable', message: 'x' } }) : json(200, { ok: true }));
  assert.deepEqual(await getWithRetry('/x', { fetchImpl: flaky, delayMs: 1 }), { ok: true });
  assert.equal(calls, 3);
  calls = 0;
  const unsupported = async () => { calls++; return json(422, { error: { code: 'unsupported_vehicle', message: 'x' } }); };
  await assert.rejects(getWithRetry('/x', { fetchImpl: unsupported, delayMs: 1 }));
  assert.equal(calls, 1);
});
test('predict sends JSON body and X-Client-Id header; numeric INR is passed through untouched', async () => {
  let seen;
  globalThis.fetch = async (url, init) => { seen = { url, init }; return json(200, { estimated_price_inr: 550000 }); };
  clearCache();
  const out = await api.predict({ make: 'A', model: 'B', year: 2015, km_driven: 1, fuel: 'Petrol', transmission: 'Manual' }, { clientId: 'abc-123-abc-123-abc' });
  assert.equal(out.estimated_price_inr, 550000);
  assert.equal(seen.url, '/api/predict'); assert.equal(seen.init.method, 'POST');
  assert.equal(seen.init.headers['X-Client-Id'], 'abc-123-abc-123-abc');
  assert.equal(JSON.parse(seen.init.body).make, 'A');
});
test('getClientId persists a random id and tolerates unavailable storage', () => {
  const store = new Map();
  const storage = { getItem: (k) => store.get(k) ?? null, setItem: (k, v) => store.set(k, v) };
  const id = getClientId(storage);
  assert.match(id, /^[0-9a-f-]{36}$/);
  assert.equal(getClientId(storage), id);
  assert.equal(getClientId({ getItem() { throw new Error('denied'); } }), null);
});
