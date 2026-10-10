import { readFile, writeFile } from 'node:fs/promises';
import { fileURLToPath } from 'node:url';
import { join } from 'node:path';
import sharp from 'sharp';

const root = fileURLToPath(new URL('../..', import.meta.url));
const diagrams = [
  {
    source: 'docs/assets/dexpot-execution.svg',
    png: 'docs/assets/dexpot-execution.png',
    webp: 'website/public/dexpot-execution.webp',
  },
  {
    source: 'docs/assets/dexpot-response-contract.svg',
    png: 'docs/assets/dexpot-response-contract.png',
    webp: 'website/public/dexpot-response-contract.webp',
  },
];

for (const diagram of diagrams) {
  const svg = await readFile(join(root, diagram.source));
  const image = sharp(svg, { density: 72 });
  await writeFile(join(root, diagram.png), await image.clone().png({ compressionLevel: 9 }).toBuffer());
  await writeFile(join(root, diagram.webp), await image.clone().resize({ width: 1200 }).webp({ quality: 88 }).toBuffer());
  console.log(`Rendered ${diagram.source} -> ${diagram.png} and ${diagram.webp}`);
}
