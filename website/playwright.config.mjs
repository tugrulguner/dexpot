import { defineConfig, devices } from '@playwright/test';

const port = process.env.PLAYWRIGHT_PORT ?? '4342';
const baseURL = process.env.PLAYWRIGHT_BASE_URL ?? `http://127.0.0.1:${port}`;

export default defineConfig({
  testDir: './tests/visual',
  outputDir: process.env.PLAYWRIGHT_OUTPUT_DIR ?? `${process.env.TMPDIR ?? './.cache'}/playwright-results`,
  fullyParallel: true,
  reporter: 'list',
  use: { ...devices['Desktop Chrome'], baseURL, screenshot: 'only-on-failure' },
  webServer: process.env.PLAYWRIGHT_BASE_URL ? undefined : {
    command: `npm run preview -- --host 127.0.0.1 --port ${port} --strictPort`,
    url: `${baseURL}/playground/`,
    reuseExistingServer: false,
    timeout: 30_000,
  },
});
