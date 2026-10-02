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
      await page.evaluate(async (value) => {
        document.documentElement.dataset.theme = value;
        await document.fonts.ready;
        await new Promise((resolve) => requestAnimationFrame(() => requestAnimationFrame(resolve)));
      }, theme);
      await expect(page.locator('main h1')).toHaveText('Request workbench');
      await expect(page.locator('main h1')).toHaveCount(1);
      await expect(page.locator('.workbench-record summary')).toContainText('Optional recorded loopback run');
      await page.locator('.workbench-record summary').click();
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
          reset: bounds('#contract-reset'),
          requestHeading: bounds('.contract-grid article:first-child h3'),
          responseHeading: bounds('.contract-grid article:last-child h3'),
          requestPre: bounds('#contract-request'),
          responsePre: bounds('#contract-response'),
          title: bounds('main h1'),
          theme: document.documentElement.dataset.theme,
          colors: Object.fromEntries(['.eyebrow', '.workbench-intro', '.pane-label', '.request-pane label', '.workbench-actions button:first-child', '#request-target', '.contract-grid h3', '.contract-note', '.run-timing', '.run-timing span', '.code-pane pre', '.contract-grid pre', '.record-details', '.record-details strong', '.workbench-record summary'].map((selector) => {
            const node = document.querySelector(selector);
            const style = getComputedStyle(node);
            return [selector, { foreground: style.color, background: style.backgroundColor }];
          })),
        };
      });
      expect(layout.document, `${width}px document overflow (${theme})`).toBeLessThanOrEqual(width);
      expect(layout.body, `${width}px body overflow (${theme})`).toBeLessThanOrEqual(width);
      for (const region of [layout.record, layout.source, layout.builder, layout.run, layout.reset]) {
        expect(region.x).toBeGreaterThanOrEqual(0);
        expect(region.right).toBeLessThanOrEqual(width + 1);
        expect(region.width).toBeGreaterThan(0);
        expect(region.height).toBeGreaterThan(0);
      }
      expect(layout.run.height).toBe(44);
      expect(layout.reset.height).toBe(44);
      expect(layout.run.y).toBe(layout.reset.y);
      if (width >= 672) {
        expect(layout.requestHeading.y).toBe(layout.responseHeading.y);
        expect(layout.requestHeading.height).toBe(layout.responseHeading.height);
        expect(layout.requestPre.y).toBe(layout.responsePre.y);
        expect(layout.requestPre.height).toBe(layout.responsePre.height);
      } else {
        expect(layout.responseHeading.y).toBeGreaterThan(layout.requestPre.y);
        expect(layout.responsePre.y).toBeGreaterThan(layout.responseHeading.y);
      }
      const actualStyles = await page.evaluate(() => ['#contract-run', '#contract-reset'].map((selector) => { const style = getComputedStyle(document.querySelector(selector)); return { font: style.font, padding: style.padding }; }));
      expect(actualStyles[0]).toEqual(actualStyles[1]);
      if (width >= 768) {
        expect(layout.source.y).toBeLessThan(900);
        expect(layout.builder.y).toBeLessThan(900);
        expect(layout.run.bottom).toBeLessThan(900);
      }
      const backgrounds = theme === 'light'
        ? { normal: '#f8f7f4', code: '#f8f7f4', button: '#087d70' }
        : { normal: '#202226', code: '#16181b', button: '#4fa89b' };
      for (const [selector, colors] of Object.entries(layout.colors)) {
        const background = selector.includes('pre') ? backgrounds.code : selector.includes('button') ? backgrounds.button : backgrounds.normal;
        const foreground = colors.foreground;
        expect(contrast(foreground, background), `${selector} contrast ${theme}`).toBeGreaterThanOrEqual(4.5);
      }
      await page.locator('#contract-run').click();
      await expect(page.locator('#contract-response')).toContainText('201');
      await expect(page.locator('#run-timing')).toContainText(/\d+\.\d{3} ms/);
      expect(await page.locator('#run-timing').innerText()).not.toContain('—');
      await page.locator('#item-price').fill('');
      await page.locator('#contract-run').click();
      await expect(page.locator('#contract-response')).toContainText('422');
      await expect(page.locator('#contract-error')).toContainText('request body');
      await expect(page.locator('#run-timing')).toContainText(/\d+\.\d{3} ms/);
      await page.locator('#contract-reset').click();
      await expect(page.locator('#contract-request')).toHaveText('Awaiting run()');
      await expect(page.locator('#contract-response')).toHaveText('No response yet.');
      await expect(page.locator('#run-timing')).toContainText('—');
      await page.emulateMedia({ reducedMotion: 'reduce' });
      expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(width);
    }
  }
});
