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

const benchmarkRecord = await readFile(join(websiteRoot, 'benchmarks/loopback-2026-10-02.md'), 'utf8');
const benchmarkLines = benchmarkRecord.split(/\r?\n/);
if (benchmarkLines[0] !== '---' || benchmarkLines[4] !== '---') {
  throw new Error('loopback benchmark record must have a closed YAML front matter block');
}
for (const value of ['p50 439 µs', 'p90 0.92 ms', 'p99 1.76 ms', '83,430 responses checked', '0 invalid statuses/bodies']) {
  if (!benchmarkRecord.includes(value)) throw new Error(`loopback benchmark record missing preserved value: ${value}`);
}
const benchmarkValidator = await readFile(join(websiteRoot, 'benchmarks/dexpot-loopback.lua'), 'utf8');
for (const value of ['status ~= 200', `'{"id":7,"name":"item-7","price":7.0}'`, 'validated_responses=%d invalid_responses=%d']) {
  if (!benchmarkValidator.includes(value)) throw new Error(`loopback benchmark response validator missing: ${value}`);
}

const failures = [];
let htmlCount = 0;
for await (const path of htmlFiles(distRoot)) {
  htmlCount += 1;
  const html = await readFile(path, 'utf8');
  const outputPath = relative(distRoot, path);
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
  if (outputPath.endsWith('examples/index.html') || outputPath.endsWith('playground/index.html')) {
    for (const token of ['BROWSER-LOCAL CONTRACT', 'examples/typed_crud.py', 'id="operation"', 'id="item-id"', 'id="item-name"', 'id="item-price"', 'id="request-target"', 'id="contract-response"', 'id="contract-run"', 'id="contract-reset"', 'Local contract preview, not a Python server.']) {
      if (!html.includes(token)) failures.push(`${outputPath}: missing playground feature ${token}`);
    }
    if (outputPath.endsWith('playground/index.html')) {
      for (const token of ['examples/typed_crud.py · create_item', 'Optional recorded loopback run', 'p50 439 µs', 'p90 0.92 ms', 'p99 1.76 ms', 'Canonical Python source ↗', 'id="run-timing"', 'Excludes Dexpot Python/server and network latency']) {
        if (!html.includes(token)) failures.push(`${outputPath}: missing playground feature ${token}`);
      }
      const playgroundHeadings = [...html.matchAll(/<h[1-6][^>]*>([\s\S]*?)<\/h[1-6]>/g)]
        .map((match) => match[1].replace(/<[^>]+>/g, '').trim());
      if (playgroundHeadings.filter((heading) => /request workbench|browser-local request workbench|typed route, from input/i.test(heading)).length !== 1) {
        failures.push(`${outputPath}: expected one canonical request-workbench heading`);
      }
      if (html.includes('Browser local request workbench') || html.includes('A typed route, from input to response.')) {
        failures.push(`${outputPath}: duplicate playground hero copy remains`);
      }
    }
    if (html.includes('recorded-local-http-execution') || html.includes('typed-crud-capture.json') || html.includes('CrudCapture')) failures.push(`${outputPath}: recording-only capture remains`);
  }
  if (outputPath.endsWith('playground/index.html') && (!html.includes('83,430 checked responses') || !html.includes('loopback-2026-10-02.md'))) {
    failures.push(`${outputPath}: missing measured latency provenance`);
  }
  if (outputPath === 'index.html' && !html.includes('href="/playground/"')) failures.push('index.html: missing direct playground link');
  if (outputPath !== '404.html' && !html.includes('href="/current-boundaries/"')) {
    failures.push(`${outputPath}: missing prominent alpha-boundary link`);
  }
  const statusTitle = 'Alpha — review boundaries before adopting';
  if (outputPath === 'index.html' && !html.includes(statusTitle)) {
    failures.push(`${outputPath}: missing primary adoption status warning`);
  }
  if (outputPath === 'index.html' && html.includes('Current status')) {
    failures.push(`${outputPath}: duplicate secondary status warning remains`);
  }
  if (!html.includes('https://modepot.io/')) {
    failures.push(`${relative(distRoot, path)}: missing canonical ModePot return link`);
  }
  if (html.includes('modepot.com')) failures.push(`${relative(distRoot, path)}: stale ModePot domain`);
  for (const token of [
    'rel="alternate" type="text/plain" href="/llms.txt"',
    'property="og:image" content="https://dexpot.modepot.io/social-card-v2.png"',
    'name="twitter:image" content="https://dexpot.modepot.io/social-card-v2.png"',
  ]) {
    if (!html.includes(token)) failures.push(`${outputPath}: missing discovery metadata ${token}`);
  }
  const jsonLd = html.match(/<script type="application\/ld\+json">([\s\S]*?)<\/script>/)?.[1];
  if (!jsonLd) {
    failures.push(`${outputPath}: missing JSON-LD`);
  } else {
    try {
      const data = JSON.parse(jsonLd);
      const types = new Set((data['@graph'] ?? [data]).map((node) => node['@type']));
      for (const type of ['SoftwareApplication', 'WebSite']) {
        if (!types.has(type)) failures.push(`${outputPath}: missing ${type} structured data`);
      }
    } catch (error) {
      failures.push(`${outputPath}: invalid JSON-LD (${error.message})`);
    }
  }
}

// Keep the narrow-screen table regression covered in the committed build gate:
// emitted CSS must retain full-width tables and allow long cell tokens to wrap.
const cssFiles = (await readdir(join(distRoot, '_astro')))
  .filter((name) => extname(name) === '.css');
const stylesheets = await Promise.all(
  cssFiles.map((name) => readFile(join(distRoot, '_astro', name), 'utf8')),
);
const tableRules = stylesheets.join('\n');
if (!/\.sl-markdown-content table\s*\{[^}]*width:\s*100%/.test(tableRules)) {
  failures.push('emitted CSS: markdown tables must remain full width');
}
if (!/\.sl-markdown-content table :is\(th,td\)\s*\{[^}]*overflow-wrap:\s*anywhere/.test(tableRules)) {
  failures.push('emitted CSS: markdown table cells must wrap long unbreakable content');
}
if (/\.sl-markdown-content table\s*\{[^}]*display:\s*table/.test(tableRules)) {
  failures.push('emitted CSS: markdown tables must not force native table display sizing');
}

const llms = await readFile(join(distRoot, 'llms.txt'), 'utf8');
if (!llms.includes('https://modepot.io/')) failures.push('llms.txt: missing canonical ModePot URL');
if (llms.includes('modepot.com')) failures.push('llms.txt: stale ModePot domain');
for (const token of ['License: MIT', 'https://pypi.org/project/dexpot/', 'Current boundaries']) {
  if (!llms.includes(token)) failures.push(`llms.txt: missing ${token}`);
}
const socialCard = await readFile(join(distRoot, 'social-card-v2.png'));
if (socialCard.readUInt32BE(16) !== 1200 || socialCard.readUInt32BE(20) !== 630) {
  failures.push('social-card-v2.png: expected 1200x630 PNG');
}
if (htmlCount === 0) failures.push('no rendered HTML files found');

if (failures.length > 0) {
  console.error('Rendered output verification failed:');
  for (const failure of failures) console.error(`- ${failure}`);
  process.exitCode = 1;
} else {
  console.log(`Verified rendered content and discovery metadata in ${htmlCount} HTML files.`);
}
