import { expect, test } from '@playwright/test';

const guides = [
  ['typed-api', 'Build a typed JSON API'],
  ['request-lifecycle', 'Trace a request through Dexpot'],
  ['deployment', 'Deploy within current boundaries'],
  ['benchmarking', 'Benchmark without overclaiming'],
];

test('build guide pages and Markdown downloads remain readable at desktop and mobile widths', async ({ page, request }) => {
  await page.setViewportSize({ width: 1280, height: 900 });
  await page.goto('/build-guides/');
  await expect(page.getByRole('heading', { name: 'Build guides', level: 1 })).toBeVisible();
  for (const [slug, title] of guides) {
    const response = await page.goto(`/guides/${slug}/`);
    expect(response?.status()).toBe(200);
    await expect(page.getByRole('heading', { name: title, level: 1 })).toBeVisible();
    await expect(page.locator('header.header a.family-home')).toHaveAttribute('href', 'https://modepot.io/');
    const themeSelect = page.locator('header.header select');
    await expect(themeSelect.locator('option')).toHaveCount(3);
    expect(await page.locator('main').evaluate((node) => getComputedStyle(node).fontFamily)).toContain('Avenir Next');
    await page.emulateMedia({ colorScheme: 'light' });
    for (const [theme, background] of [['light', 'rgb(248, 247, 244)'], ['dark', 'rgb(22, 24, 27)']]) {
      await themeSelect.selectOption(theme);
      await expect.poll(() => page.evaluate(() => getComputedStyle(document.body).backgroundColor)).toBe(background);
    }
    await expect(page.getByRole('link', { name: 'Download this guide as Markdown' })).toHaveAttribute('href', `/guides/${slug}.md`);
    const download = await request.get(`/guides/${slug}.md`);
    expect(download.status()).toBe(200);
    expect(await download.text()).toContain(`title: ${title}`);
    expect(await page.locator('main').evaluate((node) => getComputedStyle(node).fontSize)).not.toBe('0px');
  }

  await page.setViewportSize({ width: 375, height: 812 });
  for (const [slug, title] of guides) {
    await page.goto(`/guides/${slug}/`);
    await expect(page.getByRole('heading', { name: title, level: 1 })).toBeVisible();
    const dimensions = await page.locator('body').evaluate((node) => ({ scroll: node.scrollWidth, client: node.clientWidth }));
    expect(dimensions.scroll).toBeLessThanOrEqual(dimensions.client + 1);
  }
});
