import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import { createHash } from 'node:crypto';
import { fileURLToPath } from 'node:url';
import { join } from 'node:path';
import test from 'node:test';

const root = fileURLToPath(new URL('../..', import.meta.url));

test('website binds scheduler selection to serve startup after application imports', async () => {
  for (const name of ['index.mdx', 'execution-model.md', 'guides/deployment.md']) {
    const source = await readFile(join(root, 'website/src/content/docs', name), 'utf8');
    assert.ok(source.includes('when `serve()` starts'), `${name}: scheduler binding must happen at serve startup`);
    assert.ok(source.includes('after application imports'), `${name}: application imports precede selection`);
    assert.doesNotMatch(source, /selected at import time|scheduler once when the module imports|scheduling\*\* selected once when the module imports/i);
  }
  const deployment = await readFile(join(root, 'website/src/content/docs/guides/deployment.md'), 'utf8');
  assert.ok(deployment.includes('fail during import'), 'environment-limit validation remains distinct from serve-time scheduler selection');
});

test('the worker lifecycle is additive and follows the execution overview before response policy', async () => {
  for (const name of ['README.md', 'website/src/content/docs/index.mdx']) {
    const text = await readFile(join(root, name), 'utf8');
    const positions = ['dexpot-execution.', 'dexpot-worker-lifecycle.', 'dexpot-response-contract.'].map((marker) => text.indexOf(marker));
    assert.ok(positions.every((position) => position >= 0), `${name}: all three diagrams must remain present`);
    assert.ok(positions[0] < positions[1] && positions[1] < positions[2], `${name}: overview -> worker lifecycle -> response contract`);
  }
  const model = await readFile(join(root, 'website/src/content/docs/execution-model.md'), 'utf8');
  assert.ok(model.includes('## Worker lifecycle'));
  assert.ok(model.includes('Open the worker-lifecycle diagram at full size'));
  for (const phrase of ['after application imports', 'waiting does not', 'thread has exited', 'Linux', 'main/acceptor']) {
    assert.ok(model.includes(phrase), `execution-model: missing accessible lifecycle explanation: ${phrase}`);
  }
});

test('both existing diagrams retain their original SVG, PNG and WebP bytes', async () => {
  const preserved = {
    'docs/assets/dexpot-execution.svg': '0757f10b2dc378ea406cf77365c4f66097585145b8ea88b6cad105e903abebfd',
    'docs/assets/dexpot-execution.png': '9623ca1ce172ed958852fe585635ec87fb086cc56ee815f96f06c60fdc3c6c13',
    'docs/assets/dexpot-response-contract.svg': '80c4be20db7a5ce9b249deddf752ed2240411184d87bd92486dd688392bd69d8',
    'docs/assets/dexpot-response-contract.png': '82e570e46227c0da65eb9dc38e7a564d14b2396f4a288b63c80bae27ee34dcde',
    'website/public/dexpot-execution.webp': '53a5045c73d6c355c8030cd104457e925ee3aa3df22c244ec2e1899b8eb05c20',
    'website/public/dexpot-response-contract.webp': '3ef549f51327e3059be955d88f15646d23ac83c85cb3c60f3a10f706713ab8e1',
  };
  for (const [name, expected] of Object.entries(preserved)) {
    const bytes = await readFile(join(root, name));
    assert.equal(createHash('sha256').update(bytes).digest('hex'), expected, `${name}: existing artwork must remain unchanged`);
  }
});
