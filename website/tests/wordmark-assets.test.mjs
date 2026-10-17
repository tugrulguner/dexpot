import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import { resolve } from 'node:path';
import sharp from 'sharp';

const root = resolve(import.meta.dirname, '../..');
const cyan = { r: 102, g: 217, b: 255 };
async function assertRenderedCyan(path) {
  const { data, info } = await sharp(resolve(root, path)).removeAlpha().raw().toBuffer({ resolveWithObject: true });
  const social = info.height === 630;
  const left = social ? 470 : 510;
  const top = social ? 235 : 330;
  const bottom = social ? 360 : 470;
  let cyanPixels = 0;
  let amberPixels = 0;
  let prefixPixels = 0;
  for (let y = top; y < bottom; y += 1) for (let x = left; x < Math.min(info.width, 1100); x += 1) {
    const offset = (y * info.width + x) * info.channels;
    const rgb = data.subarray(offset, offset + 3);
    if (x >= left + 200 && Math.abs(rgb[0] - cyan.r) < 8 && Math.abs(rgb[1] - cyan.g) < 8 && Math.abs(rgb[2] - cyan.b) < 8) cyanPixels += 1;
    if (x >= left + 200 && Math.abs(rgb[0] - 242) < 8 && Math.abs(rgb[1] - 184) < 8 && Math.abs(rgb[2] - 75) < 8) amberPixels += 1;
    if (x < left + 100 && Math.abs(rgb[0] - 244) < 8 && Math.abs(rgb[1] - 242) < 8 && Math.abs(rgb[2] - 234) < 8) prefixPixels += 1;
  }
  assert.ok(prefixPixels > 100, `${path} must retain off-white dex prefix`);
  assert.ok(cyanPixels > 100, `${path} has no cyan pot suffix in its wordmark region`);
  assert.equal(amberPixels, 0, `${path} retains amber in the wordmark suffix region`);
}
async function assertWordmark(path) {
  const svg = await readFile(resolve(root, path), 'utf8');
  const wordmark = svg.match(/<text\b[^>]*>dex(.*?)<\/text>/s)?.[0];
  assert.ok(wordmark, `${path} has no joined dexpot wordmark`);
  assert.match(wordmark, /fill="#F4F2EA"/);
  assert.match(wordmark, /<tspan\s+fill="#66D9FF">pot<\/tspan>/);
}
for (const svg of ['assets/dexpot-lockup.svg', 'website/public/social-card.svg']) await assertWordmark(svg);
for (const image of ['assets/dexpot.png', 'website/src/assets/dexpot.webp', 'website/public/social-card-v2.png']) await assertRenderedCyan(image);
const css = await readFile(resolve(root, 'website/src/styles/custom.css'), 'utf8');
assert.match(css, /--dexpot-wordmark-light:\s*#006b8f/i);
assert.match(css, /--dexpot-wordmark-dark:\s*#66d9ff/i);
assert.match(css, /framework-wordmark span/);
assert.match(css, /site-title \.wordmark-suffix/);
const header = await readFile(resolve(root, 'website/src/components/Header.astro'), 'utf8');
assert.ok(header.includes('<span class="wordmark-suffix">pot</span>'));
console.log('Canonical, website, and social wordmarks pass cyan SVG, rendered-pixel, and light/dark HTML-branding checks.');
