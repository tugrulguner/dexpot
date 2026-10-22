import { expect, test } from '@playwright/test';

test('rendered public runtime tables and hosted roadmap preserve precise release scope', async ({ page, request }) => {
  for (const width of [1280, 375]) {
    await page.setViewportSize({ width, height: 900 });
    for (const route of ['/', '/execution-model/', '/guides/deployment/', '/project/readme/']) {
      await page.goto(route);
      await expect(page.getByRole('cell', { name: 'Free-threaded CPython (GIL disabled)', exact: true })).toHaveCount(1);
      await expect(page.getByRole('cell', { name: 'CPython with the GIL enabled', exact: true })).toHaveCount(1);
      expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
    }
    await page.goto('/project/roadmap/');
    await expect(page.locator('main')).toContainText('The Darwin FT correction shipped in v0.7.1');
    await expect(page.locator('main')).toContainText('not a direct v0.7.0-to-v0.7.1 benchmark');
    await expect(page.locator('main')).toContainText('not a cross-platform performance guarantee');
  }
  // Deployment is a canonical Markdown download; execution-model is an HTML page.
  const response = await request.get('/guides/deployment.md');
  expect(response.status()).toBe(200);
  expect(await response.text()).toContain('Free-threaded CPython (GIL disabled)');
});
