import { readdir, readFile } from 'node:fs/promises';
import { extname, join, relative } from 'node:path';
import { fileURLToPath } from 'node:url';

const websiteRoot = fileURLToPath(new URL('..', import.meta.url));
const distRoot = join(websiteRoot, 'dist');
const forbidden = [
  {
    label: 'uncompiled Starlight component import',
    pattern: /import\s+\{[^}]*\}\s+from\s+['"]@astrojs\/starlight\/components['"]/,
  },
  {
    label: 'uncompiled MDX component tag',
    pattern: /<\/?(?:Aside|Steps|Card|CardGrid)\b/,
  },
];

async function* htmlFiles(directory) {
  for (const entry of await readdir(directory, { withFileTypes: true })) {
    const path = join(directory, entry.name);
    if (entry.isDirectory()) {
      yield* htmlFiles(path);
    } else if (extname(entry.name) === '.html') {
      yield path;
    }
  }
}

const failures = [];
for await (const path of htmlFiles(distRoot)) {
  const html = await readFile(path, 'utf8');
  for (const check of forbidden) {
    if (check.pattern.test(html)) {
      failures.push(`${relative(distRoot, path)}: ${check.label}`);
    }
  }
}

if (failures.length > 0) {
  console.error('Rendered output contains uncompiled MDX syntax:');
  for (const failure of failures) console.error(`- ${failure}`);
  process.exitCode = 1;
} else {
  console.log('Rendered output contains no uncompiled Starlight components.');
}
