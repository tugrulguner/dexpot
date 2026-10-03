import assert from 'node:assert/strict';
import { spawnSync } from 'node:child_process';
import { createServer } from 'node:net';
import { dirname } from 'node:path';
import test from 'node:test';

const configPath = new URL('../../playwright.config.mjs', import.meta.url);

async function loadConfig(env = {}) {
  const script = `import config from ${JSON.stringify(configPath.href)}; process.stdout.write(JSON.stringify({ baseURL: config.use.baseURL, webServer: config.webServer }));`;
  const processEnv = { ...process.env, ...env };
  if (!Object.hasOwn(env, 'PLAYWRIGHT_BASE_URL')) delete processEnv.PLAYWRIGHT_BASE_URL;
  const result = spawnSync(process.execPath, ['--input-type=module', '-e', script], {
    cwd: dirname(new URL(configPath).pathname),
    encoding: 'utf8',
    env: processEnv,
  });
  assert.equal(result.status, 0, result.stderr);
  return JSON.parse(result.stdout);
}

test('default preview and Playwright target share a strict isolated port', async () => {
  const config = await loadConfig({ PLAYWRIGHT_PORT: '45671' });
  assert.equal(config.baseURL, 'http://127.0.0.1:45671');
  assert.match(config.webServer.command, /--port 45671 --strictPort/);
  assert.doesNotMatch(config.webServer.command, /--ignore-lock/);
  assert.equal(config.webServer.url, 'http://127.0.0.1:45671/playground/');
  assert.equal(config.webServer.reuseExistingServer, false);
});

test('strict preview binding rejects an occupied configured port', async () => {
  const server = createServer();
  await new Promise((resolve) => server.listen(0, '127.0.0.1', resolve));
  const { port } = server.address();
  try {
    const config = await loadConfig({ PLAYWRIGHT_PORT: String(port) });
    const preview = spawnSync('npm', ['run', 'preview', '--', '--host', '127.0.0.1', '--port', String(port), '--strictPort', '--ignore-lock'], {
      cwd: dirname(new URL(configPath).pathname),
      encoding: 'utf8',
      timeout: 5_000,
    });
    const output = `${preview.stdout}\n${preview.stderr}`;
    assert.equal(preview.error, undefined, `preview did not exit normally: ${preview.error?.message}`);
    assert.equal(preview.signal, null, `preview was terminated by ${preview.signal}`);
    assert.notEqual(preview.status, 0, `preview unexpectedly succeeded: ${preview.stdout}`);
    assert.match(output, /port .* already in use|EADDRINUSE|address already in use/i);
    assert.doesNotMatch(output, /trying another one|Local:\s+http:\/\/127\.0\.0\.1:\d+/i);
    assert.match(config.webServer.command, new RegExp(`--port ${port} --strictPort`));
  } finally {
    await new Promise((resolve, reject) => server.close((error) => error ? reject(error) : resolve()));
  }
});

test('explicit external base URL disables local preview startup', async () => {
  const config = await loadConfig({ PLAYWRIGHT_BASE_URL: 'http://127.0.0.1:4342' });
  assert.equal(config.baseURL, 'http://127.0.0.1:4342');
  assert.equal(config.webServer, undefined);
});
