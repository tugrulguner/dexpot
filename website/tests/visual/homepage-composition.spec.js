import { expect, test } from '@playwright/test';

const widths = [1280, 768, 390, 320];

for (const colorScheme of ['light', 'dark']) {
  test(`320px homepage code blocks are keyboard-scrollable in ${colorScheme}`, async ({ page }) => {
    await page.setViewportSize({ width: 320, height: 850 });
    await page.emulateMedia({ colorScheme, reducedMotion: 'reduce' });
    await page.goto('/');
    await page.locator('starlight-theme-select select').selectOption(colorScheme);
    const blocks = page.locator('main .sl-markdown-content pre');
    const count = await blocks.count();
    const overflowing = [];
    for (let i = 0; i < count; i++) {
      if (await blocks.nth(i).evaluate((pre) => pre.scrollWidth > pre.clientWidth)) overflowing.push(i);
    }
    expect(overflowing.length, 'homepage contains horizontally scrollable code').toBeGreaterThan(0);
    for (const index of overflowing) {
      const block = blocks.nth(index);
      let reachedByTab = false;
      for (let step = 0; step < 120; step++) {
        await page.keyboard.press('Tab');
        if (await block.evaluate((pre) => document.activeElement === pre)) { reachedByTab = true; break; }
      }
      expect(reachedByTab, `overflowing homepage code block ${index} is reachable by Tab`).toBe(true);
      const geometry = await block.evaluate((pre) => ({ tabIndex: pre.tabIndex, outline: getComputedStyle(pre).outlineStyle }));
      expect(geometry.tabIndex, `code block ${index} explicitly participates in sequential keyboard navigation`).toBe(0);
      expect(geometry.outline, `code block ${index} has visible keyboard focus`).not.toBe('none');
      for (let step = 0; step < 100; step++) {
        if (await block.evaluate((pre) => pre.scrollLeft >= pre.scrollWidth - pre.clientWidth - 1)) break;
        await page.keyboard.press('ArrowRight');
      }
      const end = await block.evaluate((pre) => ({ max: pre.scrollWidth - pre.clientWidth, left: pre.scrollLeft }));
      expect(end.left, `ArrowRight reveals the complete line in code block ${index}`).toBeGreaterThanOrEqual(end.max - 1);
      expect(await page.evaluate(() => document.documentElement.scrollWidth), 'page remains within the 320px viewport').toBeLessThanOrEqual(320);
    }
  });
}

for (const colorScheme of ['light', 'dark']) {
  test(`homepage code remains keyboard-scrollable after resizing in ${colorScheme}`, async ({ page }) => {
    await page.setViewportSize({ width: 1280, height: 850 });
    await page.emulateMedia({ colorScheme, reducedMotion: 'reduce' });
    await page.goto('/');
    await page.setViewportSize({ width: 320, height: 850 });
    await page.evaluate(() => document.fonts.ready);
    const blocks = page.locator('main .sl-markdown-content pre');
    const count = await blocks.count();
    const overflowing = [];
    for (let i = 0; i < count; i++) {
      if (await blocks.nth(i).evaluate((pre) => pre.scrollWidth > pre.clientWidth)) overflowing.push(i);
    }
    expect(overflowing.length).toBeGreaterThan(0);
    for (const index of overflowing) {
      const block = blocks.nth(index);
      let reachedByTab = false;
      for (let step = 0; step < 120; step++) {
        await page.keyboard.press('Tab');
        if (await block.evaluate((pre) => document.activeElement === pre)) { reachedByTab = true; break; }
      }
      expect(reachedByTab, `resized code block ${index} is reachable by Tab`).toBe(true);
      expect(await block.evaluate((pre) => getComputedStyle(pre).outlineStyle)).not.toBe('none');
      for (let step = 0; step < 100; step++) {
        if (await block.evaluate((pre) => pre.scrollLeft >= pre.scrollWidth - pre.clientWidth - 1)) break;
        await page.keyboard.press('ArrowRight');
      }
      const end = await block.evaluate((pre) => ({ max: pre.scrollWidth - pre.clientWidth, left: pre.scrollLeft }));
      expect(end.left).toBeGreaterThanOrEqual(end.max - 1);
      expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(320);
    }
  });

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
        await page.screenshot({ path: `${process.env.EVIDENCE_DIR}/${width}-${colorScheme}.png`, fullPage: true });
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
        return { columns: getComputedStyle(document.querySelector('.framework-hero')).gridTemplateColumns, hero: rect('.framework-hero'), copy: rect('.framework-copy'), art: rect('.framework-art'), page: document.documentElement.scrollWidth };
      });
      expect(layout.page).toBeLessThanOrEqual(width);
      expect(layout.hero.y, `${width}px framework hero top aligns with Intpot`).toBe(153);
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
      const homepageExample = page.locator('.deeper-content pre').filter({ hasText: 'from dexpot import Dex' });
      await expect(homepageExample).toBeVisible();
      await expect(homepageExample).toContainText('@app.get("/items/{item_id}", response=ItemOut)');
      const runCommand = page.locator('.deeper-content pre').filter({ hasText: 'PYTHONPATH=examples dexpot serve minimal:app' });
      await expect(runCommand).toBeVisible();
      await expect(runCommand).toContainText('dexpot serve minimal:app --host 127.0.0.1 --port 8000');
      const nextQuickstart = page.locator('main .pagination-links a[rel="next"]');
      await expect(nextQuickstart).toHaveAttribute('href', '/quick-start/');
      await expect(nextQuickstart).toContainText('Quick start');
      expect(await homepageExample.evaluate((node) => node.getBoundingClientRect().top)).toBeGreaterThan(order[3]);
      await nextQuickstart.click();
      await expect(page).toHaveURL(/\/quick-start\/$/);
      await expect(page.locator('main h1').first()).toContainText('Quick start');
    }
  });
}
