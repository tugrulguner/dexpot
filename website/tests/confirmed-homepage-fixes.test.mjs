import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import { execFileSync } from 'node:child_process';
import test from 'node:test';
const root = new URL('../', import.meta.url);
execFileSync(process.execPath,['scripts/sync-project-docs.mjs'],{cwd:root});
test('generated README preserves complete image elements and source destinations', async () => {
 const source=await readFile(new URL('../README.md',root),'utf8');
 const generated=await readFile(new URL('src/content/docs/project/readme.md',root),'utf8');
 const originals=[...source.matchAll(/<img\b[^>]*?\bsrc=["']([^"']+)["']/gi)].map(match=>match[1]).filter(target=>!/^https?:|^data:/.test(target));
 const images=[...generated.matchAll(/<img\b[^>]*?\bsrc=["']([^"']+)["']/gi)].map(match=>match[1]);
 assert.ok(originals.length>0);
 for(const target of originals)assert.ok(images.some(url=>url.startsWith('https://raw.githubusercontent.com/tugrulguner/dexpot/')&&url.endsWith(target)),`missing complete image element for ${target}`);
 for(const name of ['dexpot-execution.png','dexpot-response-contract.png'])assert.ok(generated.includes('/docs/assets/'+name));
});
test('homepage preserves header feedback and puts hero feedback after GitHub',async()=>{
 const home=await readFile(new URL('src/content/docs/index.mdx',root),'utf8');
 const header=await readFile(new URL('src/components/Header.astro',root),'utf8');
 assert.ok(header.includes('Feedback'));
 const actions=home.match(/<nav class="framework-actions"[^>]*>([\s\S]*?)<\/nav>/)?.[1];
 assert.ok(actions);
 assert.match(actions,/class="framework-action[^"\n]*feedback-entry[^"\n]*"[^>]*href="https:\/\/github\.com\/tugrulguner\/dexpot\/issues\/new/);
 assert.ok(actions.indexOf('>GitHub')<actions.indexOf('>Feedback'));
});
