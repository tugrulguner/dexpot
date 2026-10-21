import { expect, test } from '@playwright/test';

const widths = [1280, 768, 390, 320];

test('homepage diagrams render in overview-then-lifecycle-then-response order at desktop and mobile widths', async ({ page }) => {
  for (const width of [1280, 390]) {
    await page.setViewportSize({ width, height: 850 });
    await page.goto('/');
    const diagrams = page.locator('main .content-panel figure.homepage-diagram');
    await expect(diagrams).toHaveCount(3);
    await expect(diagrams.nth(0).locator('img')).toHaveAttribute('src', /dexpot-execution\.webp\?v=127306a$/);
    await expect(diagrams.nth(1).locator('img')).toHaveAttribute('src', /dexpot-worker-lifecycle\.webp\?v=071-lifecycle-v1$/);
    await expect(diagrams.nth(2).locator('img')).toHaveAttribute('src', /dexpot-response-contract\.webp\?v=070-response-v1$/);
    const positions = await diagrams.evaluateAll((nodes) => nodes.map((node) => node.getBoundingClientRect().top));
    expect(positions[0]).toBeLessThan(positions[1]);
    expect(positions[1]).toBeLessThan(positions[2]);
    await expect(page.getByText('The original execution diagram is a conceptual overview')).toBeVisible();
    await expect(page.getByText('In v0.7.0,')).toBeVisible();
  }
});

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
      await expect(actions).toHaveText(['Quick start', 'Playground', 'Roadmap', 'GitHub ↗', 'Feedback ↗']);
      expect(await actions.evaluateAll((nodes) => nodes.map((node) => node.getAttribute('href')))).toEqual(['/quick-start/', '/playground/', '/project/roadmap/', 'https://github.com/tugrulguner/dexpot', 'https://github.com/tugrulguner/dexpot/issues/new?title=Dexpot%20website%20feedback&body=Page%3A%20https%3A%2F%2Fdexpot.modepot.io%2F']);
      const roadmap = hero.getByRole('link', { name: 'Roadmap' });
      await expect(roadmap).toBeVisible();
      await roadmap.click();
      await expect(page).toHaveURL(/\/project\/roadmap\/$/);
      await expect(page.getByRole('heading', { name: 'Project roadmap', exact: true })).toBeVisible();
      await page.goBack();
      await expect(hero).toBeVisible();
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
      if (width <= 390) {
        const contentLeft = await page.locator(".sl-markdown-content").first().evaluate((node) => node.getBoundingClientRect().left);
        expect(Math.abs(layout.hero.x - contentLeft), `${width}px framework hero matches the sibling content gutter without an extra inset`).toBeLessThanOrEqual(0.5);
        expect(layout.hero.x, `${width}px framework hero retains the 16px page gutter`).toBeGreaterThanOrEqual(15.5);
        expect(layout.hero.x, `${width}px framework hero retains the 16px page gutter`).toBeLessThanOrEqual(16.5);
      }
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

test('deep homepage diagrams defer initial loading, reserve exact ratios, and decode after scrolling in cold mobile and desktop contexts', async ({ browser, baseURL }) => {
  const expected = [
    { width: '2400', height: '1350', ratio: 16 / 9 },
    { width: '2400', height: '1800', ratio: 4 / 3 },
    { width: '1200', height: '624', ratio: 25 / 13 },
  ];
  for (const width of [320, 1280]) {
    const context = await browser.newContext({ viewport: { width, height: 850 } });
    await context.route('**/*', async (route) => {
      const request = route.request();
      if (request.method() === 'POST' && /posthog|i\.posthog\.com/i.test(request.url())) return route.fulfill({ status: 204, body: '' });
      return route.continue();
    });
    const page = await context.newPage();
    try {
      await page.goto(new URL('/', baseURL).href);
      const diagrams = page.locator('main .content-panel figure.homepage-diagram img');
      await expect(diagrams).toHaveCount(expected.length);
      const initial = await diagrams.evaluateAll((images) => images.map((img) => {
        const rect = img.getBoundingClientRect();
        const src = new URL(img.currentSrc || img.src).pathname;
        return {
          loading: img.loading,
          width: img.getAttribute('width'),
          height: img.getAttribute('height'),
          top: rect.top,
          renderedWidth: rect.width,
          renderedHeight: rect.height,
          maxHeight: Number.parseFloat(getComputedStyle(img).maxHeight),
          hasPreload: [...document.querySelectorAll('link[rel="preload"][as="image"]')].some((link) => new URL(link.href).pathname === src),
        };
      }));
      for (let index = 0; index < expected.length; index++) {
        expect(initial[index].loading, `diagram ${index} uses native lazy loading at ${width}px`).toBe('lazy');
        expect(initial[index].width).toBe(expected[index].width);
        expect(initial[index].height).toBe(expected[index].height);
        expect(initial[index].top, `diagram ${index} remains below the initial viewport at ${width}px`).toBeGreaterThan(850);
        const expectedRenderedHeight = Math.min(initial[index].renderedWidth / expected[index].ratio, initial[index].maxHeight);
        expect(Math.abs(initial[index].renderedHeight - expectedRenderedHeight), `diagram ${index} uses its intrinsic ratio within the existing max-height cap`).toBeLessThan(1.5);
        expect(initial[index].hasPreload, `diagram ${index} is not explicitly preloaded`).toBe(false);
      }
      for (let index = 0; index < expected.length; index++) {
        const image = diagrams.nth(index);
        await image.scrollIntoViewIfNeeded();
        await expect.poll(() => image.evaluate(async (img) => {
          if (!img.complete || img.naturalWidth <= 0 || img.naturalHeight <= 0) return false;
          await img.decode();
          return true;
        })).toBe(true);
      }
    } finally {
      await context.close();
    }
  }
});
