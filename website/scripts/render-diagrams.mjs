import { readFile, writeFile } from 'node:fs/promises';
import { createHash } from 'node:crypto';
import { fileURLToPath } from 'node:url';
import { join } from 'node:path';
import sharp from 'sharp';

const root = fileURLToPath(new URL('../..', import.meta.url));
const diagrams = [
  {
    source: 'assets/dexpot-lockup.svg',
    png: 'assets/dexpot.png',
    webp: 'website/src/assets/dexpot.webp',
    width: 1200,
  },
  {
    source: 'website/public/social-card.svg',
    png: 'website/public/social-card-v2.png',
    width: 1200,
    height: 630,
  },
  {
    source: 'docs/assets/dexpot-worker-lifecycle.svg',
    png: 'docs/assets/dexpot-worker-lifecycle.png',
    webp: 'website/public/dexpot-worker-lifecycle.webp',
    width: 2400,
    height: 1800,
  },
  // Preserve the original execution artwork byte-for-byte; corrective artwork is additive.
  {
    source: 'docs/assets/dexpot-response-contract.svg',
    // Preserve published raster bytes while this source is unchanged. Re-encoding
    // an identical SVG on another OS can produce different PNG/WebP bytes.
    preserveSourceSha256: '80c4be20db7a5ce9b249deddf752ed2240411184d87bd92486dd688392bd69d8',
    png: 'docs/assets/dexpot-response-contract.png',
    webp: 'website/public/dexpot-response-contract.webp',
  },
];

for (const diagram of diagrams) {
  const svg = await readFile(join(root, diagram.source));
  if (diagram.preserveSourceSha256 === createHash('sha256').update(svg).digest('hex')) {
    // Missing committed assets are an error, not permission to silently replace them.
    await readFile(join(root, diagram.png));
    if (diagram.webp) await readFile(join(root, diagram.webp));
    console.log(`Preserved unchanged published artwork: ${diagram.source}`);
    continue;
  }
  let image = sharp(svg, { density: 72 });
  if (diagram.width) image = image.resize({ width: diagram.width, height: diagram.height, fit: 'fill' });
  await writeFile(join(root, diagram.png), await image.clone().png({ compressionLevel: 9 }).toBuffer());
  if (diagram.webp) {
    await writeFile(join(root, diagram.webp), await image.clone().resize({ width: diagram.width ?? 1200 }).webp({ quality: 88 }).toBuffer());
    console.log(`Rendered ${diagram.source} -> ${diagram.png} and ${diagram.webp}`);
  } else {
    console.log(`Rendered ${diagram.source} -> ${diagram.png}`);
  }
}
