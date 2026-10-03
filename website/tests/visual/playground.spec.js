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

test('run timing stays beside the action that produced it', async ({ page }) => {
  for (const width of [1280, 768, 320]) {
    await page.setViewportSize({ width, height: 900 });
    await page.goto('/playground/');
    await page.locator('#contract-run').click();
    const run = await page.locator('#contract-run').boundingBox();
    const timing = await page.locator('#run-timing').boundingBox();
    const pane = await page.locator('.request-pane').boundingBox();
    expect(timing.x).toBeGreaterThanOrEqual(pane.x);
    expect(timing.x + timing.width).toBeLessThanOrEqual(pane.x + pane.width + 1);
    expect(timing.y - run.y - run.height).toBeGreaterThanOrEqual(0);
    expect(timing.y - run.y - run.height).toBeLessThanOrEqual(24);
    if (width === 1280) expect(timing.y + timing.height).toBeLessThan(900);
  }
});

test('editing the draft invalidates the prior response and timing', async ({ page }) => {
  await page.goto('/playground/');
  for (const field of ['operation', 'item-id', 'item-name', 'item-price']) {
    await page.locator('#contract-run').click();
    await expect(page.locator('#run-timing')).toContainText(/\d+\.\d{3} ms/);
    if (field === 'operation') await page.locator('#operation').selectOption('get');
    else await page.locator(`#${field}`).fill(field === 'item-name' ? 'Changed' : '2');
    await expect(page.locator('#contract-request')).toHaveText('Awaiting run()');
    await expect(page.locator('#contract-response')).toHaveText('No response yet.');
    await expect(page.locator('#contract-error')).toHaveText('');
    await expect(page.locator('#run-timing')).toContainText('—');
    expect(await page.locator('#run-timing').innerText()).not.toMatch(/\d+\.\d{3} ms/);
  }
});

test('populated request and response panels keep matched desktop bounds', async ({ page }) => {
  for (const width of [768, 1280]) {
    await page.setViewportSize({ width, height: 900 });
    for (const theme of ['light', 'dark']) {
      await page.goto('/playground/');
      await page.evaluate(async (value) => {
        document.documentElement.dataset.theme = value;
        await document.fonts.ready;
        await new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve)));
      }, theme);
      await page.locator('#operation').selectOption('get');
      await page.locator('#contract-run').click();
      await expect(page.locator('#contract-response')).toContainText('200');
      for (const id of ['1', '999']) {
        await page.locator('#item-id').fill(id);
        await page.locator('#contract-run').click();
        await expect(page.locator('#contract-response')).toContainText(id === '1' ? '200' : '404');
        const request = await page.locator('#contract-request').boundingBox();
        const response = await page.locator('#contract-response').boundingBox();
        expect(request.y).toBe(response.y);
        expect(request.height).toBe(response.height);
        expect(request.width).toBe(response.width);
      }
    }
  }
});

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
      await expect(page.locator('.workbench-record').getByRole('link', { name: 'ModePot ↗' })).toHaveAttribute('href', 'https://modepot.io/');
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
          colors: Object.fromEntries(['.eyebrow', '.workbench-intro', '.pane-label', '.request-pane label', '.workbench-actions button:first-child', '.workbench-actions button:last-child', '#request-target', '.contract-grid h3', '.contract-note', '.run-timing', '.run-timing span', '.code-pane pre', '.contract-grid pre', '.record-details', '.record-details strong', '.workbench-record summary'].map((selector) => {
            const node = document.querySelector(selector);
            const style = getComputedStyle(node);
            let ancestor = node;
            let background = style.backgroundColor;
            while (ancestor && (background === 'transparent' || /rgba\([^)]*,\s*0(?:\.0+)?\)$/.test(background))) {
              ancestor = ancestor.parentElement;
              if (ancestor) background = getComputedStyle(ancestor).backgroundColor;
            }
            if (!ancestor) throw new Error(`No rendered opaque background for ${selector}`);
            return [selector, { foreground: style.color, background }];
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
      for (const [selector, colors] of Object.entries(layout.colors)) {
        expect(contrast(colors.foreground, colors.background), `${selector} actual rendered contrast ${theme}`).toBeGreaterThanOrEqual(4.5);
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


test('rendered family frame, theme behavior, and real-text contrast hold across homepage and docs', async ({ page }) => {
  for (const route of ['/', '/quick-start/']) {
    for (const width of [1280, 768, 320]) {
      await page.setViewportSize({ width, height: width === 320 ? 390 : width === 768 ? 768 : 900 });
      await page.emulateMedia({ colorScheme: 'dark', reducedMotion: 'reduce' });
      await page.goto(route);
      const themeSelect = page.locator('header.header select');
      await expect(themeSelect.locator('xpath=ancestor::label')).toContainText('Select theme');
      await expect(themeSelect.locator('option')).toHaveCount(3);
      await expect(page.locator('main h1')).toBeVisible();
      await page.evaluate(() => document.fonts.ready);

      for (const theme of ['light', 'dark']) {
        await themeSelect.selectOption(theme, { force: true });
        const actual = await page.evaluate(async () => {
          await document.fonts.ready;
          await new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve)));
          const opaqueBackground = (node) => {
            let current = node;
            while (current) {
              const color = getComputedStyle(current).backgroundColor;
              if (color !== 'transparent' && !/rgba\([^)]*,\s*0(?:\.0+)?\)$/.test(color)) return color;
              current = current.parentElement;
            }
            throw new Error(`No opaque background for ${node.tagName}.${node.className}`);
          };
          const sample = (selector) => {
            const node = document.querySelector(selector);
            const style = getComputedStyle(node);
            return { fg: style.color, bg: opaqueBackground(node), rect: node.getBoundingClientRect().toJSON() };
          };
          const header = document.querySelector('header.header');
          const product = header.querySelector('.site-title');
          const modepot = header.querySelector(innerWidth < 800 ? 'a.family-home-mobile' : 'a.family-home');
          const search = header.querySelector('site-search button[data-open-modal]');
          const github = [...header.querySelectorAll('a')].find(a => a.textContent.trim() === 'GitHub');
          return {
            theme: document.documentElement.dataset.theme,
            headerHeight: header.getBoundingClientRect().height,
            docWidth: document.documentElement.scrollWidth,
            bodyWidth: document.body.scrollWidth,
            font: getComputedStyle(document.body).fontFamily,
            product: product.getBoundingClientRect().toJSON(),
            modepot: modepot && { href: modepot.href, rect: modepot.getBoundingClientRect().toJSON() },
            search: search && search.getBoundingClientRect().toJSON(),
            github: github && github.getBoundingClientRect().toJSON(),
            canvas: getComputedStyle(document.body).backgroundColor,
            text: ['main h1', 'main p', 'header .site-title', 'header .right-group', 'header select'].map(sample),
            themeBoundary: (() => { const n = document.querySelector('header select'), s = getComputedStyle(n); return { border: s.borderTopColor, background: opaqueBackground(n), width: s.borderTopWidth }; })(),
            secondary: document.querySelector('.hero .actions .minimal') && (() => {
              const n = document.querySelector('.hero .actions .minimal'), s = getComputedStyle(n);
              return { ...sample('.hero .actions .minimal'), border: s.borderTopColor, width: s.borderTopWidth, radius: s.borderRadius, height: n.getBoundingClientRect().height };
            })(),
          };
        });
        expect(actual.theme).toBe(theme);
        expect(actual.headerHeight).toBe(64);
        expect(actual.docWidth).toBeLessThanOrEqual(width);
        expect(actual.bodyWidth).toBeLessThanOrEqual(width);
        expect(actual.font).toContain('Avenir Next');
        expect(actual.modepot?.href).toBe('https://modepot.io/');
        expect(actual.search.x).toBeGreaterThan(actual.product.x + actual.product.width);
        if (width >= 800) expect(actual.search.right).toBeLessThanOrEqual(actual.github.x + 1);
        for (const [index, colors] of actual.text.entries()) {
          expect(contrast(colors.fg, colors.bg), `${route} actual rendered text sample ${index} (${theme}): ${JSON.stringify(colors)}`).toBeGreaterThanOrEqual(4.5);
        }
        expect(actual.themeBoundary.width).not.toBe('0px');
        expect(contrast(actual.themeBoundary.border, actual.themeBoundary.background), `${route} theme control boundary (${theme})`).toBeGreaterThanOrEqual(3);
        if (route === '/') {
          expect(actual.secondary).toBeTruthy();
          expect(actual.secondary.height).toBeGreaterThanOrEqual(44);
          expect(actual.secondary.radius).toBe('6px');
          expect(actual.secondary.width).toBe('1px');
          expect(contrast(actual.secondary.fg, actual.secondary.bg)).toBeGreaterThanOrEqual(4.5);
          expect(contrast(actual.secondary.border, actual.secondary.bg)).toBeGreaterThanOrEqual(3);
        }
      }

      for (const [system, expected] of [['light', 'rgb(248, 247, 244)'], ['dark', 'rgb(22, 24, 27)']]) {
        await page.emulateMedia({ colorScheme: system, reducedMotion: 'reduce' });
        await themeSelect.selectOption('auto', { force: true });
        await expect.poll(() => page.evaluate(() => getComputedStyle(document.body).backgroundColor)).toBe(expected);
        await expect(themeSelect).toHaveValue('auto');
      }
    }
  }
});

test('family foundation maps shared tokens across homepage, docs, and playground', async ({ page }) => {
  for (const route of ['/', '/quick-start/', '/playground/']) {
    for (const width of [1280, 768, 320]) {
      await page.setViewportSize({ width, height: width === 320 ? 390 : width === 768 ? 768 : 900 });
      await page.emulateMedia({ colorScheme: 'dark', reducedMotion: 'reduce' });
      await page.goto(route);
      for (const theme of ['light', 'dark']) {
        const actual = await page.evaluate(async (selectedTheme) => {
          document.documentElement.dataset.theme = selectedTheme;
          await document.fonts.ready;
          await new Promise((resolve) => requestAnimationFrame(() => requestAnimationFrame(resolve)));
          const root = getComputedStyle(document.documentElement);
          const title = document.querySelector('.hero h1, main h1');
          const titleStyle = getComputedStyle(title);
          let ancestor = title;
          let background = titleStyle.backgroundColor;
          while (ancestor && (background === 'transparent' || /rgba\([^)]*,\s*0(?:\.0+)?\)$/.test(background))) {
            ancestor = ancestor.parentElement;
            if (ancestor) background = getComputedStyle(ancestor).backgroundColor;
          }
          const header = document.querySelector('header.header');
          const primary = document.querySelector('.hero .actions .primary');
          return {
            canvas: root.getPropertyValue('--mp-canvas-light').trim(),
            darkCanvas: root.getPropertyValue('--mp-canvas-dark').trim(),
            accent: root.getPropertyValue('--mp-accent-light').trim(),
            font: root.getPropertyValue('--mp-font').trim(),
            headerHeight: Math.round(header.getBoundingClientRect().height),
            headingTransform: titleStyle.textTransform,
            headingSize: parseFloat(titleStyle.fontSize),
            headingContrast: { foreground: titleStyle.color, background },
            documentWidth: document.documentElement.scrollWidth,
            bodyWidth: document.body.scrollWidth,
            primary: primary && { height: primary.getBoundingClientRect().height, radius: getComputedStyle(primary).borderRadius },
          };
        }, theme);
        expect(actual.canvas).toBe('#f8f7f4');
        expect(actual.darkCanvas).toBe('#16181b');
        expect(actual.accent).toBe('#14665f');
        expect(actual.font).toContain('Avenir Next');
        expect(actual.headerHeight).toBe(64);
        expect(actual.headingTransform).toBe('none');
        expect(actual.headingSize).toBeLessThanOrEqual(route === '/' ? 56 : 40);
        expect(contrast(actual.headingContrast.foreground, actual.headingContrast.background)).toBeGreaterThanOrEqual(4.5);
        expect(actual.documentWidth).toBeLessThanOrEqual(width);
        expect(actual.bodyWidth).toBeLessThanOrEqual(width);
        if (actual.primary) {
          expect(actual.primary.height).toBeGreaterThanOrEqual(44);
          expect(actual.primary.radius).toBe('6px');
        }
      }
    }
  }
});
