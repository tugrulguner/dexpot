import { expect, test } from '@playwright/test';

test('worker lifecycle remains readable and additive in both themes and narrow layouts', async ({ page }) => {
  for (const theme of ['light', 'dark']) {
    await page.addInitScript((selected) => localStorage.setItem('starlight-theme', selected), theme);
    for (const route of ['/', '/execution-model/']) {
      for (const width of [1280, 375]) {
        await page.setViewportSize({ width, height: 900 });
        await page.goto(route);
        await expect(page.locator('html')).toHaveAttribute('data-theme', theme);
        const diagram = page.getByRole('img', { name: /^Dexpot worker lifecycle:/ });
        await diagram.scrollIntoViewIfNeeded();
        await expect(diagram).toBeVisible();
        await expect.poll(() => diagram.evaluate((image) => image.complete && image.naturalWidth)).toBe(2400);
        await expect(page.getByRole('link', { name: 'Open the worker-lifecycle diagram at full size' }).first()).toHaveAttribute('href', '/dexpot-worker-lifecycle.webp?v=071-lifecycle-v1');
        const body = await page.locator('body').evaluate((node) => ({ width: node.clientWidth, scroll: node.scrollWidth }));
        expect(body.scroll).toBeLessThanOrEqual(body.width + 1);
        const box = await diagram.boundingBox();
        expect(box.width).toBeLessThanOrEqual(width);
        expect(Math.abs(box.height - box.width * 1800 / 2400), 'lifecycle uses its full intrinsic ratio rather than shrinking inside a short image cap').toBeLessThan(1.5);
        if (route === '/') {
          const sources = await page.locator('figure.homepage-diagram img').evaluateAll((images) => images.map((image) => new URL(image.src).pathname));
          expect(sources).toEqual(['/dexpot-execution.webp', '/dexpot-worker-lifecycle.webp', '/dexpot-response-contract.webp']);
        } else {
          await expect(page.locator('main')).toContainText('only after the thread has exited');
          await expect(page.locator('main')).toContainText('main/acceptor');
        }
      }
    }
  }
});

test('deployment HTML and Markdown agree on serve-time mode binding without moving configuration validation', async ({ page, request }) => {
  await page.goto('/guides/deployment/');
  await expect(page.locator('main')).toContainText('when serve() starts, after application imports');
  await expect(page.locator('main')).toContainText('fail during import');
  const response = await request.get('/guides/deployment.md');
  expect(response.status()).toBe(200);
  const text = await response.text();
  expect(text).toContain('when `serve()` starts, after application imports');
  expect(text).not.toContain('selected at import time');
});
