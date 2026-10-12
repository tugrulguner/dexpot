import { test, expect } from '@playwright/test';
import { gunzipSync } from 'node:zlib';

const sentinels = [
  'UTM_SENTINEL', 'CLICK_SENTINEL', 'HASH_SENTINEL', 'REFERRER_SENTINEL',
  'REF_HASH_SENTINEL', 'INPUT_SENTINEL', 'CAMPAIGN_SENTINEL', 'DOC_HASH_SENTINEL',
  'PERSISTED_UTM_SENTINEL', 'PERSISTED_CLICK_SENTINEL', 'PERSISTED_SESSION_SENTINEL',
  'PERSISTED_SESSION_CLICK_SENTINEL', 'PERSISTED_REFERRER_SENTINEL',
];

test('SDK outbound payloads omit playground inputs, URL secrets, and campaign values', async ({ browser }) => {
  const context = await browser.newContext({
    userAgent: 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/135.0.0.0 Safari/537.36',
  });
  await context.addInitScript(() => {
    Object.defineProperty(navigator, 'webdriver', { get: () => undefined });
    Object.defineProperty(navigator, 'userAgentData', { get: () => ({
      brands: [{ brand: 'Not A(Brand', version: '8' }, { brand: 'Chromium', version: '135' }, { brand: 'Google Chrome', version: '135' }],
      mobile: false, platform: 'macOS',
      getHighEntropyValues: async () => ({
        brands: [{ brand: 'Not A(Brand', version: '8' }, { brand: 'Chromium', version: '135' }, { brand: 'Google Chrome', version: '135' }],
        fullVersionList: [{ brand: 'Not A(Brand', version: '8.0.0.0' }, { brand: 'Chromium', version: '135.0.0.0' }, { brand: 'Google Chrome', version: '135.0.0.0' }],
        platform: 'macOS', platformVersion: '15.0.0', architecture: 'arm', model: '', mobile: false, bitness: '64', wow64: false,
      }),
    }) });
    Object.defineProperty(document, 'referrer', { get: () => 'https://referrer.example/path?secret=REFERRER_SENTINEL#REF_HASH_SENTINEL' });
    localStorage.setItem('phc_qXkp5FBQfrqHQwkqf3ys8iSoGoMYw2tpTHXGugXJhP8V_posthog', JSON.stringify({
      distinct_id: 'persisted-test-person', $initial_utm_source: 'PERSISTED_UTM_SENTINEL',
      $initial_gclid: 'PERSISTED_CLICK_SENTINEL', $session_entry_utm_source: 'PERSISTED_SESSION_SENTINEL',
      $session_entry_gclid: 'PERSISTED_SESSION_CLICK_SENTINEL', $initial_referrer: 'https://persisted.example/?secret=PERSISTED_REFERRER_SENTINEL',
    }));
  });
  const page = await context.newPage();
  const outgoing = [];
  page.on('request', (request) => {
    if (!request.url().startsWith('https://us.i.posthog.com/')) return;
    const raw = request.postDataBuffer();
    const compressed = raw?.[0] === 0x1f && raw?.[1] === 0x8b;
    outgoing.push({ url: request.url(), body: raw ? (compressed ? gunzipSync(raw).toString('utf8') : raw.toString('utf8')) : '' });
  });
  await context.route('https://us.i.posthog.com/**', async (route) => {
    if (route.request().method() === 'POST') {
      await route.fulfill({ status: 200, contentType: 'application/json', body: '{}' });
      return;
    }
    await route.continue();
  });

  await page.goto('/playground/?utm_source=UTM_SENTINEL&gclid=CLICK_SENTINEL#HASH_SENTINEL', { waitUntil: 'networkidle' });
  await expect(page.locator('#contract-run')).toBeVisible();
  const decodeEvents = () => outgoing
    .filter(({ url }) => /\/e\//.test(url))
    .flatMap(({ body }) => {
      try {
        const parsed = JSON.parse(body);
        return Array.isArray(parsed.batch) ? parsed.batch : Array.isArray(parsed) ? parsed : [parsed];
      } catch { return []; }
    });
  const pageOrigin = await page.evaluate(() => location.origin);
  await expect.poll(() => decodeEvents().some(({ event, properties }) =>
    event === '$pageview' && properties.$current_url === `${pageOrigin}/playground/`
  )).toBeTruthy();
  const outcomeEvents = () => decodeEvents().filter(({ event }) =>
    event === 'playground_preview_started' || event === 'playground_preview_completed'
  );
  expect(outcomeEvents()).toEqual([]);

  // Create a real local item, read that returned ID, then exercise an actual 404.
  await page.locator('#operation').selectOption('create');
  await page.locator('#item-name').fill('INPUT_SENTINEL');
  await page.locator('#item-price').fill('12.5');
  await page.locator('#contract-run').click();
  await expect(page.locator('#contract-response')).toContainText('201');
  const createdItem = JSON.parse(await page.locator('#contract-response').innerText()).body;
  expect(createdItem).toMatchObject({ name: 'INPUT_SENTINEL', price: 12.5 });

  await page.locator('#operation').selectOption('get');
  await page.locator('#item-id').fill(String(createdItem.id));
  await page.locator('#contract-run').click();
  await expect(page.locator('#contract-response')).toContainText('200');
  expect(JSON.parse(await page.locator('#contract-response').innerText()).body).toEqual(createdItem);

  await page.locator('#item-id').fill('999');
  await page.locator('#contract-run').click();
  await expect(page.locator('#contract-response')).toContainText('404');
  await expect(page.locator('#contract-error')).toHaveText('item not found');
  await expect.poll(() => outcomeEvents().length).toBe(6);
  await page.goto('/quick-start/?campaign=CAMPAIGN_SENTINEL#DOC_HASH_SENTINEL', { waitUntil: 'networkidle' });
  await expect.poll(() => decodeEvents().some(({ event, properties }) =>
    event === '$pageview' && properties.$current_url === `${pageOrigin}/quick-start/`
  )).toBeTruthy();

  const payloadText = JSON.stringify(outgoing);
  for (const sentinel of sentinels) expect(payloadText, `${sentinel} leaked via SDK request`).not.toContain(sentinel);
  expect(outgoing.some(({ url }) => /\/flags\/?(?:\?|$)/.test(url))).toBeFalsy();
  const outcomes = outcomeEvents();
  expect(outcomes.map(({ event }) => event)).toEqual([
    'playground_preview_started', 'playground_preview_completed',
    'playground_preview_started', 'playground_preview_completed',
    'playground_preview_started', 'playground_preview_completed',
  ]);
  const starts = outcomes.filter(({ event }) => event === 'playground_preview_started');
  const completions = outcomes.filter(({ event }) => event === 'playground_preview_completed');
  expect(starts).toHaveLength(3);
  expect(completions).toHaveLength(3);
  const attemptIds = starts.map(({ properties }) => properties.attempt_id);
  expect(new Set(attemptIds).size).toBe(3);
  for (let index = 0; index < 3; index += 1) {
    expect(starts[index].properties).toMatchObject({ project: 'dexpot', mode: 'crud', attempt_id: attemptIds[index] });
    expect(completions[index].properties.attempt_id).toBe(attemptIds[index]);
    expect(completions[index].properties).toMatchObject({ project: 'dexpot', mode: 'crud' });
  }
  expect(completions.map(({ properties }) => properties.result)).toEqual(['success', 'success', 'rejected']);
  expect(completions[2].properties.failure_class).toBe('not_found');
  expect(completions.slice(0, 2).every(({ properties }) => !('failure_class' in properties))).toBeTruthy();
  expect(payloadText).not.toContain('INPUT_SENTINEL');

  const config = await page.evaluate(() => ({
    capturing: posthog.is_capturing(), optedOut: posthog.has_opted_out_capturing(),
    saveCampaign: posthog.config.save_campaign_params, saveReferrer: posthog.config.save_referrer,
    flagsDisabled: posthog.config.advanced_disable_flags, capturePageview: posthog.config.capture_pageview, capturePageleave: posthog.config.capture_pageleave,
    recordingDisabled: posthog.config.disable_session_recording,
    personProfiles: posthog.config.person_profiles,
  }));
  expect(config).toMatchObject({
    capturing: true, optedOut: false, saveCampaign: false, saveReferrer: false, flagsDisabled: true,
    capturePageview: true, capturePageleave: true, recordingDisabled: true,
    personProfiles: 'identified_only',
  });
  await context.close();
});
