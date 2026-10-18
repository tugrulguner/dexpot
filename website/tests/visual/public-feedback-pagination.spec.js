import { expect, test } from '@playwright/test';

const route = '/quick-start/';
const widths = [1280, 1050, 768, 390, 320];

for (const width of widths) {
  test(`Starlight pagination and canonical feedback survive the custom footer at ${width}px`, async ({ page }) => {
    await page.setViewportSize({ width, height: 900 });
    await page.goto(`${route}?private_input=must-not-leak#private-fragment`);

    const pagination = page.locator('.pagination-links');
    await expect(pagination.locator('a[rel="prev"]')).toBeVisible();
    await expect(pagination.locator('a[rel="next"]')).toBeVisible();

    const feedback = page.locator('footer.public-feedback a');
    await feedback.scrollIntoViewIfNeeded();
    await expect(feedback).toHaveAttribute('target', '_blank');
    await expect(feedback).toHaveAttribute('rel', 'noopener noreferrer');
    const issue = new URL(await feedback.getAttribute('href'));
    expect(issue.origin + issue.pathname).toBe('https://github.com/tugrulguner/dexpot/issues/new');
    expect(issue.searchParams.get('title')).toBe('Dexpot website feedback');
    expect(issue.searchParams.get('body')).toBe('Page: https://dexpot.modepot.io/quick-start/');
    expect(issue.href).not.toContain('private_input');
    expect(issue.href).not.toContain('private-fragment');

    const bounds = await feedback.boundingBox();
    expect(bounds.width).toBeGreaterThanOrEqual(44);
    expect(bounds.height).toBeGreaterThanOrEqual(44);
    await feedback.focus();
    expect(await feedback.evaluate((node) => getComputedStyle(node).outlineStyle)).not.toBe('none');
    expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(width);
  });
}

 test('canonical issue context and pagination remain under Light, Dark, and Auto', async ({ page }) => {
  await page.setViewportSize({ width: 1280, height: 900 });
  await page.goto(route);
  const theme = page.locator('starlight-theme-select select:visible').first();
  for (const mode of ['light', 'dark', 'auto']) {
    await theme.selectOption(mode);
    await expect(page.locator('.pagination-links a[rel="next"]')).toBeVisible();
    expect(await page.locator('footer.public-feedback a').getAttribute('href')).toContain('quick-start');
  }
});
