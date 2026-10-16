import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import { resolve } from 'node:path';
import sharp from 'sharp';

const root = resolve(import.meta.dirname, '../..');
const amber = { r: 242, g: 184, b: 75 };

async function assertRenderedAmber(path) {
  const { data, info } = await sharp(resolve(root, path)).removeAlpha().raw().toBuffer({ resolveWithObject: true });
  let amberPixels = 0;
  for (let offset = 0; offset < data.length; offset += info.channels) {
    if (Math.abs(data[offset] - amber.r) < 8 && Math.abs(data[offset + 1] - amber.g) < 8 && Math.abs(data[offset + 2] - amber.b) < 8) amberPixels += 1;
  }
  assert.ok(amberPixels > 20, `${path} contains no rendered amber wordmark pixels`);
}

async function assertWordmark(svgPath) {
  const svg = await readFile(resolve(root, svgPath), 'utf8');
  const wordmark = svg.match(/<text\b[^>]*>dex(.*?)<\/text>/s)?.[0];
  assert.ok(wordmark, `${svgPath} has no joined dexpot wordmark`);
  assert.match(wordmark, /fill="#F4F2EA"/);
  assert.match(wordmark, /<tspan\s+fill="#F2B84B">pot<\/tspan>/);
}

for (const svg of ['assets/dexpot-lockup.svg', 'website/public/social-card.svg']) await assertWordmark(svg);
for (const image of ['assets/dexpot.png', 'website/src/assets/dexpot.webp', 'website/public/social-card-v2.png']) await assertRenderedAmber(image);
console.log('Canonical, website, and social wordmarks pass SVG and rendered-pixel checks.');
