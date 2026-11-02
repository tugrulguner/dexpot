import { expect, test } from '@playwright/test';
import { gotoProjectPage } from './project-navigation.mjs';

test('project content navigation does not wait for third-party status badges', async ({ page }) => {
  test.setTimeout(10_000);
  page.setDefaultNavigationTimeout(3_000);
  let release;
  let reached;
  const held = new Promise(resolve => { release = resolve; });
  const requested = new Promise(resolve => { reached = resolve; });
  await page.route('https://github.com/tugrulguner/dexpot/actions/workflows/ci.yml/badge.svg', async route => {
    reached();
    await held;
    await route.abort();
  });
  try {
    await gotoProjectPage(page, '/project/readme/');
    await requested;
    await expect(page.getByRole('cell', { name: 'Free-threaded CPython (GIL disabled)', exact: true })).toHaveCount(1);
    expect(await page.evaluate(() => document.readyState)).not.toBe('complete');
  } finally {
    release();
    await page.unrouteAll({ behavior: 'wait' });
  }
});
