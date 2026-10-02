import { defineConfig, devices } from '@playwright/test';

const baseURL = process.env.PLAYWRIGHT_BASE_URL ?? 'http://127.0.0.1:4342';

export default defineConfig({
  testDir: './tests/visual',
  outputDir: process.env.PLAYWRIGHT_OUTPUT_DIR ?? `${process.env.TMPDIR ?? './.cache'}/playwright-results`,
  fullyParallel: true,
  reporter: 'list',
  use: { ...devices['Desktop Chrome'], baseURL, screenshot: 'only-on-failure' },
  webServer: process.env.PLAYWRIGHT_BASE_URL ? undefined : {
    command: 'npm run preview -- --host 127.0.0.1 --port 4342 --ignore-lock',
    url: `${baseURL}/playground/`,
    reuseExistingServer: !process.env.CI,
    timeout: 30_000,
  },
});
