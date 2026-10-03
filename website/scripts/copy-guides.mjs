import { cp, mkdir } from 'node:fs/promises';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';

const root = fileURLToPath(new URL('..', import.meta.url));
const docs = join(root, 'src/content/docs/guides');
const downloads = join(root, 'dist/guides');
for (const name of ['typed-api', 'request-lifecycle', 'deployment', 'benchmarking']) {
  const source = join(docs, `${name}.md`);
  const target = join(downloads, `${name}.md`);
  await mkdir(dirname(target), { recursive: true });
  await cp(source, target);
}
console.log('Copied canonical guide Markdown into the build output.');
