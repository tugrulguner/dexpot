import test from 'node:test';
import assert from 'node:assert/strict';
import { createOutcomeTracker } from '../src/scripts/playground-outcomes.mjs';

test('emits paired, unique lifecycle events with a bounded privacy-safe contract', () => {
  const events = [];
  let id = 0;
  const tracker = createOutcomeTracker('dexpot', (name, properties) => events.push({ name, properties }), () => `attempt-${++id}`);
  const first = tracker.start('crud');
  tracker.complete(first, 'rejected', 'not_found');
  const second = tracker.start('crud');
  tracker.complete(second, 'success');
  assert.deepEqual(events.map(({ name }) => name), ['playground_preview_started', 'playground_preview_completed', 'playground_preview_started', 'playground_preview_completed']);
  assert.deepEqual(events.map(({ properties }) => properties.attempt_id), ['attempt-1','attempt-1','attempt-2','attempt-2']);
  assert.deepEqual(events[1].properties, { project: 'dexpot', mode: 'crud', attempt_id: 'attempt-1', result: 'rejected', failure_class: 'not_found' });
  assert.deepEqual(events[3].properties, { project: 'dexpot', mode: 'crud', attempt_id: 'attempt-2', result: 'success' });
  assert.equal(tracker.complete(first, 'success'), false);
});

test('rejects unbounded project, mode, result, and failure values', () => {
  const capture = () => {};
  assert.throws(() => createOutcomeTracker('other', capture), /project/);
  const tracker = createOutcomeTracker('dexpot', capture);
  assert.throws(() => tracker.start('user supplied mode'), /mode/);
  const attempt = tracker.start('crud');
  assert.throws(() => tracker.complete(attempt, 'free text'), /result/);
});
