import test from 'node:test';
import assert from 'node:assert/strict';
import { sanitizeAnalyticsEvent } from '../src/scripts/analytics-privacy.js';

test('sanitizes URL and acquisition fields across the whole envelope, preserving Date', () => {
  const timestamp = new Date('2026-10-11T12:00:00.000Z');
  const event = {
    timestamp,
    properties: {
      $current_url: 'https://dexpot.modepot.io/playground/?secret=QUERY_SENTINEL#HASH_SENTINEL',
      $initial_url: 'https://dexpot.modepot.io/playground/?secret=INITIAL_SENTINEL',
      $referrer: 'https://outside.example/path?secret=REFERRER_SENTINEL#fragment',
      $referring_domain: 'outside.example',
      $set: { $initial_referrer: 'https://outside.example/?secret=SET_SENTINEL', utm_source: 'CAMPAIGN_SENTINEL' },
    $session_entry_utm_source: 'SESSION_UTM_SENTINEL', $session_entry_gclid: 'SESSION_CLICK_SENTINEL',
      $session_exit_gad_source: 'GAD_SENTINEL', $initial_epik: 'EPIK_SENTINEL', $session_entry_mc_cid: 'MC_SENTINEL',
      $set_once: { $initial_referring_domain: 'outside.example', gclid: 'CLICK_SENTINEL', $initial_gclid: 'INITIAL_CLICK_SENTINEL', $initial_utm_source: 'INITIAL_UTM_SENTINEL' },
    },
  };
  const result = sanitizeAnalyticsEvent(event);
  assert.equal(result.timestamp, timestamp);
  assert.equal(result.properties.$current_url, 'https://dexpot.modepot.io/playground/');
  assert.equal(result.properties.$initial_url, 'https://dexpot.modepot.io/playground/');
  assert.equal(result.properties.$referrer, 'https://outside.example/path');
  assert.equal(result.properties.$referring_domain, 'outside.example');
  assert.equal(result.properties.$set.$initial_referrer, 'https://outside.example/');
  assert.equal(result.properties.$set.utm_source, undefined);
  assert.equal(result.properties.$set_once.$initial_referring_domain, 'outside.example');
  assert.equal(result.properties.$set_once.gclid, undefined);
  assert.equal(result.properties.$set_once.$initial_utm_source, undefined);
  assert.equal(result.properties.$set.$utm_medium, undefined);
  assert.equal(JSON.stringify(result).includes('SENTINEL'), false);
});

test('drops unknown and noncanonical URLs rather than preserving them', () => {
  const result = sanitizeAnalyticsEvent({ properties: {
    $current_url: 'javascript:alert(1)', $initial_url: 'https://evil.example/private?x=1',
    $referrer: 'not a url', $initial_referrer: 'https://outside.example/a?x=1',
  } });
  assert.equal(result.properties.$current_url, undefined);
  assert.equal(result.properties.$initial_url, 'https://evil.example/private');
  assert.equal(result.properties.$referrer, undefined);
  assert.equal(result.properties.$initial_referrer, 'https://outside.example/a');
});