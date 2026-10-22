import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import { fileURLToPath } from 'node:url';
import { join } from 'node:path';
import test from 'node:test';

const root = fileURLToPath(new URL('../..', import.meta.url));

test('public runtime summaries distinguish a free-threaded build from disabled-GIL serving', async () => {
  for (const path of ['README.md', 'website/src/content/docs/index.mdx', 'website/src/content/docs/execution-model.md', 'website/src/content/docs/guides/deployment.md']) {
    const source = await readFile(join(root, path), 'utf8');
    const text = source.replace(/\s+/g, ' ');
    assert.ok(!/Free-threaded builds (?:use|intentionally remain)/i.test(text), `${path}: build type alone must not imply the selected scheduler`);
    const rows = source.split('\n').filter((line) => /^\|/.test(line) && /one process/i.test(line));
    assert.ok(rows.length, `${path}: missing FT serving row`);
    assert.ok(rows.every((line) => /GIL disabled|_is_gil_enabled\(\).*False/.test(line.split('|')[1])), `${path}: explicitly qualify the FT serving row by actual GIL state`);
  }
});

test('roadmap distinguishes shipped v0.7.1 mechanics from bounded pre-release benchmark evidence', async () => {
  const roadmap = await readFile(join(root, 'ROADMAP.md'), 'utf8');
  assert.ok(roadmap.includes('The Darwin FT correction shipped in v0.7.1'));
  assert.ok(roadmap.includes('not a direct v0.7.0-to-v0.7.1 benchmark'));
  assert.ok(roadmap.includes('not a cross-platform performance guarantee'));
  assert.ok(roadmap.includes('all 18 macOS FT flat/nested/mixed capacity and fixed-load trials'));
  const readme = await readFile(join(root, 'README.md'), 'utf8');
  assert.ok(readme.includes('Consolidate the already-shipped request-aware response handling and output policy'));
});
