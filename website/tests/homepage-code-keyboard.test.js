import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import vm from 'node:vm';

test('homepage observer releases old targets on every Astro navigation', () => {
  const listeners = new Map();
  const observers = [];
  let content = { querySelectorAll: () => [] };
  class ResizeObserver {
    constructor(callback) { this.callback = callback; this.targets = new Set(); observers.push(this); }
    observe(target) { this.targets.add(target); }
    disconnect() { this.targets.clear(); }
  }
  const document = {
    readyState: 'complete', querySelectorAll: () => [],
    querySelector: () => content,
    addEventListener: (name, handler) => listeners.set(name, handler),
  };
  vm.runInNewContext(readFileSync(new URL('../public/scripts/homepage-code-keyboard.js', import.meta.url), 'utf8'), { document, ResizeObserver, window: { addEventListener() {} } });
  for (let index = 0; index < 4; index++) {
    const oldContent = content;
    content = { querySelectorAll: () => [] };
    listeners.get('astro:page-load')();
    assert.ok(observers.every(observer => !observer.targets.has(oldContent)), 'detached content must be released');
    assert.equal(observers.filter(observer => observer.targets.size > 0).length, 1);
  }
  content = null;
  listeners.get('astro:page-load')();
  assert.ok(observers.every(observer => observer.targets.size === 0), 'leaving content must release all targets');
});
