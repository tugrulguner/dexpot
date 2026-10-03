import assert from 'node:assert/strict';
import { readFile, readdir } from 'node:fs/promises';
import { join } from 'node:path';
import { fileURLToPath } from 'node:url';

const root = fileURLToPath(new URL('..', import.meta.url));
const dist = join(root, 'dist');
const names = ['typed-api', 'request-lifecycle', 'deployment', 'benchmarking'];
for (const name of names) {
  const source = await readFile(join(root, 'src/content/docs/guides', `${name}.md`), 'utf8');
  const download = await readFile(join(dist, 'guides', `${name}.md`), 'utf8');
  assert.equal(download, source, `${name}: Markdown download differs from canonical guide source`);
  assert.equal((source.match(/^```/gm) ?? []).length % 2, 0, `${name}: unbalanced fenced code`);
  const html = await readFile(join(dist, 'guides', name, 'index.html'), 'utf8');
  assert.match(html, new RegExp(`href="/guides/${name}\\.md"`), `${name}: missing Markdown download link`);
}

const pages = new Map();
async function scan(dir) {
  for (const entry of await readdir(dir, { withFileTypes: true })) {
    const path = join(dir, entry.name);
    if (entry.isDirectory()) await scan(path);
    else if (entry.name.endsWith('.html')) {
      const rel = path.slice(dist.length + 1);
      const html = await readFile(path, 'utf8');
      pages.set(rel, html);
    }
  }
}
await scan(dist);
for (const name of ['build-guides', 'guides/typed-api', 'guides/request-lifecycle', 'guides/deployment', 'guides/benchmarking']) {
  assert.ok(pages.has(`${name}/index.html`), `missing emitted page: ${name}`);
}
for (const [path, html] of pages) {
  for (const match of html.matchAll(/href="(\/[^"?#]*)(?:#([^"?]*))?"/g)) {
    const route = match[1];
    if (route.endsWith('.md') || /\.[a-z0-9]+$/i.test(route)) {
      const file = join(dist, route.slice(1));
      await readFile(file);
      continue;
    }
    const target = route.endsWith('/') ? `${route.slice(1)}index.html` : `${route.slice(1)}/index.html`;
    assert.ok(pages.has(target) || target === 'index.html', `${path}: broken local route ${route}`);
    if (match[2] && pages.has(target)) {
      const ids = new Set([...pages.get(target).matchAll(/\bid="([^"]+)"/g)].map((item) => item[1]));
      assert.ok(ids.has(decodeURIComponent(match[2])), `${path}: broken local anchor ${route}#${match[2]}`);
    }
  }
}
console.log(`Verified ${names.length} canonical Markdown downloads, guide routes, and local links/anchors across ${pages.size} HTML pages.`);
