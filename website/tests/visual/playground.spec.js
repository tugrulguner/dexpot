import { test, expect } from '@playwright/test';

const contrast = (foreground, background) => {
  const luminance = (color) => {
    const hex = color.match(/^#([\da-f]{3}|[\da-f]{6})$/i)?.[1];
    const channels = hex
      ? (hex.length === 3 ? [...hex].map((value) => value + value) : hex.match(/../g)).map((value) => parseInt(value, 16))
      : color.match(/[\d.]+/g).slice(0, 3).map(Number);
    const [r, g, b] = channels.map((v) => {
      const channel = v / 255;
      return channel <= 0.04045 ? channel / 12.92 : ((channel + 0.055) / 1.055) ** 2.4;
    });
    return 0.2126 * r + 0.7152 * g + 0.0722 * b;
  };
  const a = luminance(foreground);
  const b = luminance(background);
  return (Math.max(a, b) + 0.05) / (Math.min(a, b) + 0.05);
};

test('playground first fold, controls, palette contrast, and responsive bounds', async ({ page }) => {
  for (const width of [320, 768, 1280]) {
    await page.setViewportSize({ width, height: 900 });
    for (const theme of ['light', 'dark']) {
      await page.goto('/playground/');
      await page.evaluate((value) => { document.documentElement.dataset.theme = value; }, theme);
      await expect(page.locator('main h1')).toHaveText('Request workbench');
      await expect(page.locator('main h1')).toHaveCount(1);
      await expect(page.getByText('SEPARATE LOCAL SERVER RUN · NOT THIS PREVIEW')).toBeVisible();
      await expect(page.getByText('p50 439 µs')).toBeVisible();
      await expect(page.getByRole('link', { name: /Canonical Python source/ })).toHaveAttribute('href', /examples\/typed_crud\.py/);
      await expect(page.getByRole('link', { name: 'ModePot ↗' })).toHaveAttribute('href', 'https://modepot.io/');
      await expect(page.locator('.code-pane pre code')).toContainText('def create_item(item: ItemIn) -> tuple[int, Item]:');
      await expect(page.locator('#operation')).toBeVisible();
      await expect(page.locator('#item-id')).toBeVisible();
      await expect(page.locator('#item-name')).toBeVisible();
      await expect(page.locator('#item-price')).toBeVisible();
      await expect(page.locator('#contract-run')).toBeVisible();

      const layout = await page.evaluate(() => {
        const bounds = (selector) => {
          const { x, y, width, height, right, bottom } = document.querySelector(selector).getBoundingClientRect();
          return { x, y, width, height, right, bottom };
        };
        return {
          viewport: innerWidth,
          document: document.documentElement.scrollWidth,
          body: document.body.scrollWidth,
          record: bounds('.workbench-record'),
          source: bounds('.code-pane pre'),
          builder: bounds('.request-pane'),
          run: bounds('#contract-run'),
          title: bounds('main h1'),
          theme: document.documentElement.dataset.theme,
          colors: Object.fromEntries(['.eyebrow', '.workbench-intro', '.pane-label', '.request-pane label', '.workbench-actions button:first-child', '#request-target', '.contract-grid h3', '.contract-note', '.record-context', '.playground-context', '.code-pane pre', '.contract-grid pre', '.workbench-record .record-label', '.workbench-record strong', '.workbench-record a'].map((selector) => {
            const node = document.querySelector(selector);
            const style = getComputedStyle(node);
            return [selector, { foreground: style.color, background: style.backgroundColor }];
          })),
        };
      });
      expect(layout.document, `${width}px document overflow (${theme})`).toBeLessThanOrEqual(width);
      expect(layout.body, `${width}px body overflow (${theme})`).toBeLessThanOrEqual(width);
      for (const region of [layout.record, layout.source, layout.builder, layout.run]) {
        expect(region.x).toBeGreaterThanOrEqual(0);
        expect(region.right).toBeLessThanOrEqual(width + 1);
        expect(region.width).toBeGreaterThan(0);
        expect(region.height).toBeGreaterThan(0);
      }
      if (width >= 768) {
        expect(layout.source.y).toBeLessThan(900);
        expect(layout.builder.y).toBeLessThan(900);
        expect(layout.run.bottom).toBeLessThan(900);
      }
      const backgrounds = theme === 'light'
        ? { normal: '#f8f6f0', code: '#ffffff', button: '#003b50' }
        : { normal: '#111722', code: '#070a12', button: '#66d9ff' };
      for (const [selector, colors] of Object.entries(layout.colors)) {
        const background = selector.includes('pre') ? backgrounds.code : selector.includes('button') ? backgrounds.button : backgrounds.normal;
        const foreground = selector.includes('button') ? (theme === 'light' ? '#ffffff' : '#06111a') : colors.foreground;
        expect(contrast(foreground, background), `${selector} contrast ${theme}`).toBeGreaterThanOrEqual(4.5);
      }
      await page.locator('#contract-run').click();
      await expect(page.locator('#contract-response')).toContainText('201');
      await page.emulateMedia({ reducedMotion: 'reduce' });
      expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(width);
    }
  }
});
