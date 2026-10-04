import { expect, test } from '@playwright/test';

const resources = [
  ['ModePot', 'https://modepot.io/'],
  ['GitHub', 'https://github.com/tugrulguner/dexpot'],
  ['Community', 'https://discord.gg/u3AANZr6RG'],
  ['About Tugrul', 'https://tugrul.modepot.io/'],
];
const routes = ['/', '/quick-start/', '/playground/', '/404/'];
const widths = [1280, 768, 401, 400, 390, 320];

async function settle(page) {
  await page.evaluate(async () => {
    await document.fonts.ready;
    await new Promise((resolve) => requestAnimationFrame(() => requestAnimationFrame(resolve)));
  });
}

function contrast(foreground, background) {
  const channels = (color) => {
    const srgb = color.match(/color\(srgb\s+([\d.]+)\s+([\d.]+)\s+([\d.]+)/i);
    if (srgb) return srgb.slice(1).map((channel) => Number(channel) * 255);
    const hex = color.match(/^#([\da-f]{3}|[\da-f]{6})$/i)?.[1];
    if (hex) return (hex.length === 3 ? [...hex].map((value) => value + value) : hex.match(/../g)).map((value) => parseInt(value, 16));
    const values = color.match(/[\d.]+/g)?.slice(0, 3).map(Number);
    if (!values || values.length !== 3) throw new Error(`Unsupported computed color: ${color}`);
    return values;
  };
  const luminance = (color) => {
    const [r, g, b] = channels(color).map((value) => {
      const channel = value / 255;
      return channel <= 0.04045 ? channel / 12.92 : ((channel + 0.055) / 1.055) ** 2.4;
    });
    return 0.2126 * r + 0.7152 * g + 0.0722 * b;
  };
  const a = luminance(foreground);
  const b = luminance(background);
  return (Math.max(a, b) + 0.05) / (Math.min(a, b) + 0.05);
}

test('family navigation stays prominent, ordered, and accessible across routes, breakpoints, and themes', async ({ page }) => {
  for (const route of routes) {
    for (const width of widths) {
      const height = width === 320 ? 390 : width === 768 ? 768 : 900;
      await page.setViewportSize({ width, height });
      await page.emulateMedia({ colorScheme: 'dark', reducedMotion: 'reduce' });
      await page.goto(route);
      await settle(page);
      const header = page.locator('header.header');
      const familyLink = header.locator(`a[href="${resources[0][1]}"]:visible`).first();
      await expect(familyLink).toHaveText('ModePot');
      await expect(page.getByRole('heading', { level: 1 }).first()).toBeVisible();

      if (width >= 1280) {
        const desktopHeaderOrder = await page.evaluate(() => {
          const navigation = document.querySelector('.family-links');
          const theme = document.querySelector('starlight-theme-select');
          return !theme || Boolean(navigation && navigation.compareDocumentPosition(theme) & Node.DOCUMENT_POSITION_FOLLOWING);
        });
        expect(desktopHeaderOrder, 'family navigation must precede theme control like the Intpot reference').toBe(true);
        const familyLinkStyle = await header.locator('.family-links a').first().evaluate((node) => ({ fontSize: getComputedStyle(node).fontSize, fontWeight: getComputedStyle(node).fontWeight }));
        expect(familyLinkStyle, 'family link size/weight matches Intpot').toEqual({ fontSize: '16px', fontWeight: '400' });
        const navLinks = resources.map(([name]) => header.locator('.family-links').getByRole('link', { name, exact: true }));
        for (let index = 0; index < navLinks.length; index += 1) {
          await expect(navLinks[index]).toBeVisible();
          await expect(navLinks[index]).toHaveAttribute('href', resources[index][1]);
          const box = await navLinks[index].boundingBox();
          expect(box.width, `${resources[index][0]} target width`).toBeGreaterThanOrEqual(44);
          expect(box.height, `${resources[index][0]} target height`).toBeGreaterThanOrEqual(44);
          if (index > 0) {
            const previous = await navLinks[index - 1].boundingBox();
            expect(box.x).toBeGreaterThan(previous.x);
          }
          const receivesPointer = await navLinks[index].evaluate((node) => {
            const bounds = node.getBoundingClientRect();
            const hit = document.elementFromPoint(bounds.x + bounds.width / 2, bounds.y + bounds.height / 2);
            return hit === node || node.contains(hit);
          });
          expect(receivesPointer, `${resources[index][0]} center is unobscured`).toBe(true);
        }
        const controls = await header.locator('a:visible, button:visible, select:visible').evaluateAll((nodes) => nodes.map((node) => ({
          label: node.innerText || node.getAttribute('aria-label') || node.tagName,
          width: node.getBoundingClientRect().width,
          height: node.getBoundingClientRect().height,
        })));
        for (const control of controls) {
          expect(control.width, `${control.label} target width`).toBeGreaterThanOrEqual(44);
          expect(control.height, `${control.label} target height`).toBeGreaterThanOrEqual(44);
        }
      } else {
        await expect(header.locator('.family-links')).toBeHidden();
        await expect(header.locator('.site-title')).toBeVisible();
        const mobileControls = await header.locator('a:visible, button:visible, select:visible').evaluateAll((nodes) => nodes.map((node) => {
          const bounds = node.getBoundingClientRect();
          const hit = document.elementFromPoint(bounds.x + bounds.width / 2, bounds.y + bounds.height / 2);
          return {
            label: node.innerText || node.getAttribute('aria-label') || node.tagName,
            width: bounds.width,
            height: bounds.height,
            x: bounds.x,
            right: bounds.right,
            unobscured: hit === node || node.contains(hit),
          };
        }));
        mobileControls.sort((left, right) => left.x - right.x);
        for (let index = 0; index < mobileControls.length; index += 1) {
          const control = mobileControls[index];
          expect(control.width, `${control.label} mobile width`).toBeGreaterThanOrEqual(44);
          expect(control.height, `${control.label} mobile height`).toBeGreaterThanOrEqual(44);
          expect(control.unobscured, `${control.label} center is unobscured`).toBe(true);
          if (index > 0) expect(control.x, `${control.label} starts after the previous control`).toBeGreaterThanOrEqual(mobileControls[index - 1].right);
        }
        const menu = page.getByRole('button', { name: 'Menu', exact: true });
        await expect(menu).toBeVisible();
        await expect(menu).toHaveAttribute('aria-expanded', 'false');
        await menu.focus();
        await page.keyboard.press('Enter');
        const menuRegion = page.locator('#family-mobile-menu');
        await expect(menu).toHaveAttribute('aria-expanded', 'true');
        await expect(menuRegion).toBeVisible();
        const menuLinks = resources.slice(1).map(([name]) => menuRegion.getByRole('link', { name, exact: true }));
        for (let index = 0; index < menuLinks.length; index += 1) {
          await expect(menuLinks[index]).toBeVisible();
          await expect(menuLinks[index]).toHaveAttribute('href', resources[index + 1][1]);
          const box = await menuLinks[index].boundingBox();
          expect(box.height, `${resources[index + 1][0]} mobile target`).toBeGreaterThanOrEqual(44);
          expect(box.y + box.height, `${resources[index + 1][0]} is at the top of the menu`).toBeLessThan(height);
        }
        await page.keyboard.press('Escape');
        await expect(menu).toHaveAttribute('aria-expanded', 'false');
        await expect(menu).toBeFocused();
        expect(await menu.evaluate((node) => getComputedStyle(node).outlineWidth)).toBe('2px');
        await menu.evaluate((node) => node.blur());
      }

      const theme = header.locator('starlight-theme-select select');
      for (const [systemTheme, selectedTheme] of [['dark', 'light'], ['light', 'dark']]) {
        await page.emulateMedia({ colorScheme: systemTheme, reducedMotion: 'reduce' });
        await theme.selectOption(selectedTheme);
        await expect.poll(() => page.locator('html').getAttribute('data-theme')).toBe(selectedTheme);
        if (route === '/' && width === 1280 && selectedTheme === 'dark') {
          await settle(page);
          await page.screenshot({ path: `${process.env.EVIDENCE_DIR}/home-1280-dark.png`, fullPage: false });
        }
      }
      await page.emulateMedia({ colorScheme: 'dark', reducedMotion: 'reduce' });
      await theme.selectOption('auto');
      await expect.poll(() => page.locator('html').getAttribute('data-theme')).toBe('dark');
      await page.emulateMedia({ colorScheme: 'light', reducedMotion: 'reduce' });
      await expect.poll(() => page.locator('html').getAttribute('data-theme')).toBe('light');
      await settle(page);

      const rendered = await page.evaluate(() => {
        const opaqueBackground = (node) => {
          let current = node;
          while (current) {
            const color = getComputedStyle(current).backgroundColor;
            if (color !== 'transparent' && !/rgba\([^)]*,\s*0(?:\.0+)?\)$/.test(color)) return color;
            current = current.parentElement;
          }
          throw new Error('No opaque background found');
        };
        return {
          documentWidth: document.documentElement.scrollWidth,
          bodyWidth: document.body.scrollWidth,
          viewport: innerWidth,
          headerHeight: document.querySelector('header.header').getBoundingClientRect().height,
          themeBoundary: (() => {
            const node = document.querySelector('starlight-theme-select select');
            const style = getComputedStyle(node);
            return { foreground: style.borderTopColor, background: style.backgroundColor };
          })(),
          menuBoundary: (() => {
            const node = document.querySelector('.family-menu-button');
            if (!node.getClientRects().length) return null;
            const style = getComputedStyle(node);
            return { foreground: style.borderTopColor, background: style.backgroundColor };
          })(),
          navText: [...document.querySelectorAll('.family-links a, .family-home-mobile')].filter((node) => node.getClientRects().length).map((node) => {
            const style = getComputedStyle(node);
            return { text: node.textContent.trim(), foreground: style.color, background: opaqueBackground(node) };
          }),
        };
      });
      expect(rendered.documentWidth).toBeLessThanOrEqual(width);
      expect(rendered.bodyWidth).toBeLessThanOrEqual(width);
      expect(rendered.headerHeight).toBe(64);
      expect(contrast(rendered.themeBoundary.foreground, rendered.themeBoundary.background), `${route} theme control boundary`).toBeGreaterThanOrEqual(3);
      if (rendered.menuBoundary) expect(contrast(rendered.menuBoundary.foreground, rendered.menuBoundary.background), `${route} Menu boundary`).toBeGreaterThanOrEqual(3);
      for (const item of rendered.navText) {
        expect(contrast(item.foreground, item.background), `${route} ${item.text} text contrast`).toBeGreaterThanOrEqual(4.5);
      }

      if (route === '/' && width === 1280) {
        const creator = page.getByRole('link', { name: 'Created by Tugrul Guner', exact: true });
        await expect(creator).toHaveAttribute('href', 'https://tugrul.modepot.io/');
        await expect(creator).toBeVisible();
        const box = await creator.boundingBox();
        expect(box.y + box.height).toBeLessThanOrEqual(900);
        await page.screenshot({ path: `${process.env.EVIDENCE_DIR}/home-1280-light.png`, fullPage: true });
      }
      if (route === '/' && width === 320) {
        await page.setViewportSize({ width: 320, height: 850 });
        await settle(page);
        const creator = page.getByRole('link', { name: 'Created by Tugrul Guner', exact: true });
        const box = await creator.boundingBox();
        expect(box.y + box.height).toBeLessThanOrEqual(850);
        await page.screenshot({ path: `${process.env.EVIDENCE_DIR}/home-320-first-fold.png`, fullPage: false });
      }
    }
  }
});
