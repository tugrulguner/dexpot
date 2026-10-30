import { expect, test } from '@playwright/test';
import { gotoProjectPage } from './project-navigation.mjs';

for (const width of [1280, 390, 320]) {
  for (const theme of ['light', 'dark']) {
    test(`built hero feedback and README links at ${width}px ${theme}`, async ({ page, request }, info) => {
      await page.setViewportSize({ width, height: 900 });
      await page.addInitScript((selected) => localStorage.setItem('starlight-theme', selected), theme);
      await page.goto('/');
      await expect(page.locator('html')).toHaveAttribute('data-theme', theme);
      const heroFeedback = page.locator('.framework-actions a.feedback-entry');
      await expect(heroFeedback).toHaveText('Feedback ↗');
      await expect(heroFeedback).toHaveAttribute('href', /^https:\/\/github\.com\/tugrulguner\/dexpot\/issues\/new\?/);
      await expect(heroFeedback).toHaveAttribute('target', '_blank');
      await expect(heroFeedback).toHaveCSS('min-height', '44px');
      await expect(page.locator('.family-home-mobile[aria-label^="Feedback"]')).toHaveCount(1);
      expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
      await page.screenshot({path: info.outputPath(`dexpot-home-${width}-${theme}.png`)});

      await gotoProjectPage(page, '/project/readme/');
      const diagrams = page.locator('a[href*="/docs/assets/dexpot-"]');
      await expect(diagrams).toHaveCount(3);
      for (const link of await diagrams.all()) {
        await expect(link).toHaveAttribute('href', /^https:\/\/raw\.githubusercontent\.com\/tugrulguner\/dexpot\/[0-9a-f]{40}\/docs\/assets\/dexpot-(execution|worker-lifecycle|response-contract)\.png/);
        await expect(link.locator('img')).toBeVisible();
        await expect.poll(() => link.locator('img').evaluate((image) => image.naturalWidth)).toBeGreaterThan(0);
        if (width === 1280 && theme === 'light') {
          const response = await request.get(await link.getAttribute('href'));
          expect(response.status()).toBe(200);
          expect(response.headers()['content-type']).toContain('image/png');
        }
      }
      await page.screenshot({ path: info.outputPath(`dexpot-${width}-${theme}.png`), fullPage: true });
    });
  }
}
