import { expect, test } from '@playwright/test';

const routes = ['/', '/quick-start/', '/playground/'];
const widths = [1280, 768, 390];
const palette = {
  light: { accent: 'rgb(0, 107, 143)', wordmark: 'rgb(0, 107, 143)', button: 'rgb(0, 107, 143)', ink: 'rgb(255, 255, 255)' },
  dark: { accent: 'rgb(102, 217, 255)', wordmark: 'rgb(102, 217, 255)', button: 'rgb(102, 217, 255)', ink: 'rgb(24, 26, 29)' },
};

function contrast(foreground, background) {
  const linear = (color) => color.match(/[\d.]+/g).slice(0, 3).map(Number).map((channel) => {
    const value = channel / 255;
    return value <= 0.04045 ? value / 12.92 : ((value + 0.055) / 1.055) ** 2.4;
  });
  const lum = (color) => linear(color).reduce((sum, channel, index) => sum + channel * [0.2126, 0.7152, 0.0722][index], 0);
  const [a, b] = [lum(foreground), lum(background)].sort((left, right) => right - left);
  return (a + 0.05) / (b + 0.05);
}

test('Dexpot brand actions and accents use cyan, not the former teal, across rendered routes', async ({ page }) => {
  for (const route of routes) {
    for (const width of widths) {
      await page.setViewportSize({ width, height: 900 });
      await page.goto(route);
      const theme = page.locator('starlight-theme-select select:visible').first();
      for (const mode of ['light', 'dark']) {
        await theme.selectOption(mode);
        await expect.poll(() => page.locator('html').getAttribute('data-theme')).toBe(mode);
        const actual = await page.evaluate(() => {
          const root = getComputedStyle(document.documentElement);
          const primary = document.querySelector('.framework-action.primary, .hero .actions .primary');
          const brandedLink = document.querySelector('.installation-strip a, .playground-context a, .sl-markdown-content a[href^="/route-contract/"]');
          const suffix = document.querySelector('.site-title .wordmark-suffix, .framework-wordmark span');
          const buttonStyle = primary ? getComputedStyle(primary) : null;
          return {
            accent: root.getPropertyValue('--mp-accent-' + (document.documentElement.dataset.theme === 'dark' ? 'dark' : 'light')).trim(),
            buttonBg: buttonStyle?.backgroundColor ?? null,
            buttonInk: buttonStyle?.color ?? null,
            buttonHover: buttonStyle?.filter ?? null,
            suffix: getComputedStyle(suffix).color,
            link: getComputedStyle(brandedLink).color,
            error: root.getPropertyValue('--mp-error-' + (document.documentElement.dataset.theme === 'dark' ? 'dark' : 'light')).trim(),
          };
        });
        expect(actual.accent).toBe(mode === 'light' ? '#006b8f' : '#66d9ff');
        if (route === '/') {
          expect(actual.buttonBg).toBe(palette[mode].button);
          expect(actual.buttonInk).toBe(palette[mode].ink);
        }
        expect(actual.suffix).toBe(palette[mode].wordmark);
        expect(actual.link).toBe(palette[mode].accent);
        if (route === '/') expect(actual.buttonHover).toBe('none');
        if (route === '/') expect(contrast(actual.buttonInk, actual.buttonBg)).toBeGreaterThanOrEqual(4.5);
        expect(actual.error).toBe(mode === 'light' ? '#a4262b' : '#ff9b9b');
        await page.keyboard.press('Tab');
        await page.evaluate(() => document.activeElement?.blur());
        if (route === '/') {
          const focused = page.locator('.framework-action.primary, .hero .actions .primary').first();
          await focused.focus();
          const outline = await focused.evaluate((node) => getComputedStyle(node).outlineColor);
          expect(outline).toBe(palette[mode].wordmark);
        }
      }
    }
  }
});
