import { expect, test } from '@playwright/test';

const widths = [1280, 768, 390, 320];

for (const colorScheme of ['light', 'dark']) {
  test(`framework homepage composition matches the reference in ${colorScheme}`, async ({ page }) => {
    for (const width of widths) {
      await page.setViewportSize({ width, height: 850 });
      await page.emulateMedia({ colorScheme, reducedMotion: 'reduce' });
      await page.goto('/');
      await page.evaluate(() => document.fonts.ready);
      const hero = page.locator('.framework-hero');
      await expect(hero).toBeVisible();
      if (process.env.EVIDENCE_DIR) {
        const { mkdirSync } = await import('node:fs');
        mkdirSync(process.env.EVIDENCE_DIR, { recursive: true });
        await page.screenshot({ path: `${process.env.EVIDENCE_DIR}/${width}-${colorScheme}.png` });
      }
      await expect(hero.getByRole('heading', { level: 1 })).toHaveText('Synchronous APIs. GIL or free-threaded.');
      const copy = hero.locator('.framework-copy');
      await expect(copy).toBeVisible();
      const art = hero.locator('.framework-art img');
      await expect(art).toBeVisible();
      await expect(art).toHaveAttribute('alt', /synchronous Python APIs adapt execution/);
      await expect.poll(() => art.evaluate((image) => ({ complete: image.complete, naturalWidth: image.naturalWidth, naturalHeight: image.naturalHeight }))).toEqual({ complete: true, naturalWidth: 1200, naturalHeight: 900 });
      const actions = hero.locator('.framework-actions a');
      await expect(actions).toHaveText(['Quick start', 'Playground', 'GitHub ↗']);
      expect(await actions.evaluateAll((nodes) => nodes.map((node) => node.getAttribute('href')))).toEqual(['/quick-start/', '/playground/', 'https://github.com/tugrulguner/dexpot']);
      const attribution = hero.getByRole('link', { name: 'Created by Tugrul Guner' });
      await expect(attribution).toHaveAttribute('href', 'https://tugrul.modepot.io/');
      const layout = await page.evaluate(() => {
        const rect = (selector) => {
          const { x, y, right, bottom } = document.querySelector(selector).getBoundingClientRect();
          return { x, y, right, bottom };
        };
        return { columns: getComputedStyle(document.querySelector('.framework-hero')).gridTemplateColumns, copy: rect('.framework-copy'), art: rect('.framework-art'), page: document.documentElement.scrollWidth };
      });
      expect(layout.page).toBeLessThanOrEqual(width);
      if (width > 390) {
        expect(layout.art.x).toBeGreaterThanOrEqual(layout.copy.right);
        expect(layout.art.y).toBeLessThan(layout.copy.bottom);
      } else {
        expect(layout.copy.y).toBeLessThan(layout.art.y);
        expect(layout.copy.bottom).toBeLessThanOrEqual(layout.art.y);
        expect(layout.columns.split(' ').length).toBe(1);
      }
      for (const action of await actions.all()) {
        const box = await action.boundingBox();
        expect(box.height).toBeGreaterThanOrEqual(44);
      }
      const install = page.locator('.installation-strip');
      await expect(install.locator('code')).toHaveText('pip install "dexpot[cli]"');
      await expect(install.getByRole('link')).toHaveAttribute('href', '/quick-start/');
      const notice = page.locator('.starlight-aside--caution').filter({ hasText: 'Dexpot is alpha software' });
      await expect(notice).toBeVisible();
      const demo = page.locator('.project-demo');
      await expect(demo).toContainText('Browser-local');
      await expect(demo).toContainText('Python');
      const order = await page.locator('main .content-panel').last().evaluate((node) => {
        const selectors = ['.framework-hero', '.installation-strip', '.starlight-aside--caution', '.project-demo', '.deeper-content'];
        return selectors.map((selector) => [...node.querySelectorAll(selector)].at(-1).getBoundingClientRect().top);
      });
      expect(order[0]).toBeLessThan(order[1]);
      expect(order[1]).toBeLessThan(order[2]);
      expect(order[2]).toBeLessThan(order[3]);
      expect(order[3]).toBeLessThan(order[4]);
    }
  });
}
