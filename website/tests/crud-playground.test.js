import test from 'node:test';
import assert from 'node:assert/strict';
import { createState, execute, measureRun } from '../src/scripts/crud-playground.js';
test('measured runs use the injected clock around execution on every invocation', () => {
  const readings = [10, 13.25, 20, 24.5];
  const clock = () => readings.shift();
  const result = measureRun(() => 'first', clock);
  assert.deepEqual(result, { value: 'first', elapsedMs: 3.25 });
  const invalidRun = measureRun(() => { throw new Error('invalid request'); }, clock);
  assert.equal(invalidRun.elapsedMs, 4.5);
  assert.equal(invalidRun.error.message, 'invalid request');
});
const run = (state, operation, fields = {}) => execute(state, { operation, id: 1, name: 'thing', price: 2, ...fields });
test('draft edits cannot mutate state; starter GET and reset baseline', () => {
  const state = createState();
  assert.deepEqual(state.items.get(1), { id: 1, name: 'starter', price: 9.99 });
  assert.equal(run(state, 'get').result.response.status, 200);
  assert.equal(state.items.size, 1);
});
test('create/update/get/delete exactly match example status and body contracts', () => {
  let state = createState();
  let out = run(state, 'create', { name: 'new', price: 3 }); state = out.state;
  assert.deepEqual(out.result.response, { status: 201, body: { id: 2, name: 'new', price: 3 } });
  out = run(state, 'update', { id: 2, name: 'changed', price: 4 }); state = out.state;
  assert.deepEqual(out.result.response, { status: 200, body: { id: 2, name: 'changed', price: 4 } });
  out = run(state, 'delete', { id: 2 }); state = out.state;
  assert.deepEqual(out.result.response, { status: 200, body: { deleted: 2 } });
  out = run(state, 'create', { name: 'again', price: 5 });
  assert.equal(out.result.response.body.id, 3);
  assert.equal(run(state, 'get', { id: 2 }).result.response.body.detail, 'item not found');
  assert.deepEqual(run(state, 'update', { id: 90 }).result.response, { status: 404, body: { detail: 'item not found' } });
  assert.deepEqual(run(state, 'delete', { id: 90 }).result.response, { status: 404, body: { detail: 'item not found' } });
});
test('empty, nonfinite, fractional ID/price invalid; no overwrite; live item cap', () => {
  let state = createState();
  for (const price of [Number.NaN, Infinity]) assert.equal(run(state, 'create', { price }).result.response.status, 422);
  assert.deepEqual(run(state, 'get', { id: 1.5 }).result.response, { status: 422, body: { detail: 'invalid int for item_id' } });
  assert.equal(run(state, 'get', { id: 0 }).result.response.status, 404);
  state = run(state, 'delete', { id: 1 }).state;
  state = run(state, 'create').state;
  assert.equal(state.items.has(1), false);
  assert.equal(state.items.has(2), true);
  for (let i = 0; i < 19; i++) state = run(state, 'create').state;
  assert.equal(state.items.size, 20);
  assert.equal(run(state, 'create').result.response.status, 422);
});
