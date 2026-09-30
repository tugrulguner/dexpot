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

const requiredPosthogConfig = [
  "posthog.init('phc_qXkp5FBQfrqHQwkqf3ys8iSoGoMYw2tpTHXGugXJhP8V'",
  "api_host:'https://us.i.posthog.com'",
  "defaults:'2026-05-30'",
  "person_profiles:'identified_only'",
  'capture_pageview:true',
  'capture_pageleave:true',
  "dom_event_allowlist:['click']",
  "element_allowlist:['a','button']",
  'disable_session_recording:true',
];

const failures = [];
let htmlCount = 0;
for await (const path of htmlFiles(distRoot)) {
  htmlCount += 1;
  const html = await readFile(path, 'utf8');
  for (const check of forbidden) {
    if (check.pattern.test(html)) {
      failures.push(`${relative(distRoot, path)}: ${check.label}`);
    }
  }
  for (const setting of requiredPosthogConfig) {
    if (!html.includes(setting)) {
      failures.push(`${relative(distRoot, path)}: missing PostHog setting ${setting}`);
    }
  }
  if ((html.match(/posthog\.init\(/g) ?? []).length !== 1) {
    failures.push(`${relative(distRoot, path)}: expected exactly one PostHog initialization`);
  }
  if (!html.includes('https://modepot.io/')) {
    failures.push(`${relative(distRoot, path)}: missing canonical ModePot return link`);
  }
  if (html.includes('modepot.com')) failures.push(`${relative(distRoot, path)}: stale ModePot domain`);
}

const llms = await readFile(join(distRoot, 'llms.txt'), 'utf8');
if (!llms.includes('https://modepot.io/')) failures.push('llms.txt: missing canonical ModePot URL');
if (llms.includes('modepot.com')) failures.push('llms.txt: stale ModePot domain');
if (htmlCount === 0) failures.push('no rendered HTML files found');

if (failures.length > 0) {
  console.error('Rendered output verification failed:');
  for (const failure of failures) console.error(`- ${failure}`);
  process.exitCode = 1;
} else {
  console.log('Rendered output contains no uncompiled Starlight components.');
}
