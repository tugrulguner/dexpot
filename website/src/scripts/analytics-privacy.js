const URL_FIELDS = new Set([
  '$current_url', '$initial_url', '$referrer', '$initial_referrer',
  '$pageview_url', '$pageleave_url', '$session_entry_url', '$session_exit_url',
  '$session_entry_referrer', '$session_exit_referrer',
  'url', 'current_url', 'initial_url', 'referrer', 'destination',
]);
const DOMAIN_FIELDS = new Set(['$referring_domain', '$initial_referring_domain']);
const PRIVATE_ACQUISITION = /^(?:utm_.+|gclid|dclid|fbclid|msclkid|ttclid|li_fat_id|twclid|sccid|campaign(?:_id)?|ad_id|adgroup(?:_id)?|creative|keyword|matchtype|network|gad_source|mc_cid|gclsrc|igshid|rdt_cid|epik|qclid|irclid|_kx)$/i;
const isPrivateAcquisition = (key) => PRIVATE_ACQUISITION.test(key.replace(/^(?:\$)?(?:initial|session_entry|session_exit)_/i, '').replace(/^\$/i, ''));

function safeUrl(value) {
  if (typeof value !== 'string') return undefined;
  try {
    const url = new URL(value);
    if (url.protocol !== 'https:' && url.protocol !== 'http:') return undefined;
    if (url.username || url.password) return undefined;
    return `${url.origin}${url.pathname}`;
  } catch { return undefined; }
}

function clean(value, key = '') {
  if (value instanceof Date) return value;
  if (URL_FIELDS.has(key)) return safeUrl(value);
  if (DOMAIN_FIELDS.has(key)) {
    if (typeof value !== 'string') return undefined;
    try { return new URL(`https://${value}`).hostname === value ? value : undefined; } catch { return undefined; }
  }
  if (isPrivateAcquisition(key)) return undefined;
  if (Array.isArray(value)) return value.map((item) => clean(item)).filter((item) => item !== undefined);
  if (value && typeof value === 'object') {
    const result = {};
    for (const [childKey, child] of Object.entries(value)) {
      const sanitized = clean(child, childKey);
      if (sanitized !== undefined) result[childKey] = sanitized;
    }
    return result;
  }
  return value;
}

export function sanitizeAnalyticsEvent(event) {
  return clean(event);
}

export const analyticsSanitizerBootstrap = `(()=>{const u=new Set(['$current_url','$initial_url','$referrer','$initial_referrer','$pageview_url','$pageleave_url','$session_entry_url','$session_exit_url','$session_entry_referrer','$session_exit_referrer','url','current_url','initial_url','referrer','destination']),d=new Set(['$referring_domain','$initial_referring_domain']),p=/^(?:utm_.+|gclid|dclid|fbclid|msclkid|ttclid|li_fat_id|twclid|sccid|campaign(?:_id)?|ad_id|adgroup(?:_id)?|creative|keyword|matchtype|network|gad_source|mc_cid|gclsrc|igshid|rdt_cid|epik|qclid|irclid|_kx)$/i;function c(v,k=''){if(v instanceof Date)return v;if(u.has(k)){if(typeof v!=='string')return;try{let x=new URL(v);return ['https:','http:'].includes(x.protocol)&&!x.username&&!x.password?x.origin+x.pathname:undefined}catch{return}}if(d.has(k)){if(typeof v!=='string')return;try{return new URL('https://'+v).hostname===v?v:undefined}catch{return}}if(p.test(k.replace(/^(?:\\$)?(?:initial|session_entry|session_exit)_/i,'').replace(/^\\$/i,'')))return;if(Array.isArray(v))return v.map(x=>c(x)).filter(x=>x!==undefined);if(v&&typeof v==='object'){let r={};for(let [a,b]of Object.entries(v)){let x=c(b,a);if(x!==undefined)r[a]=x}return r}return v}window.dexpotSanitizeAnalyticsEvent=c})();`;

// Shared full initialization source consumed by every Astro document layout.
export const analyticsBootstrap = `!function(t,e){var o,n,p,r;e.__SV||(window.posthog=e,e._i=[],e.init=function(i,s,a){function g(t,e){var o=e.split(".");2==o.length&&(t=t[o[0]],e=o[1]),t[e]=function(){t.push([e].concat(Array.prototype.slice.call(arguments,0)))}}(p=t.createElement("script")).type="text/javascript",p.crossOrigin="anonymous",p.async=!0,p.src=s.api_host.replace(".i.posthog.com","-assets.i.posthog.com")+"/static/array.js",(r=t.getElementsByTagName("script")[0]).parentNode.insertBefore(p,r);var u=e;for(void 0!==a?u=e[a]=[]:a="posthog",u.people=u.people||[],u.toString=function(t){var e="posthog";return"posthog"!==a&&(e+="."+a),t||(e+=" (stub)"),e},u.people.toString=function(){return u.toString(1)+".people (stub)"},o="init capture identify alias people.set people.set_once people.unset reset opt_in_capturing opt_out_capturing has_opted_in_capturing has_opted_out_capturing clear_opt_in_out_capturing onFeatureFlags getFeatureFlag getFeatureFlagPayload isFeatureEnabled reloadFeatureFlags updateEarlyAccessFeatureEnrollment getEarlyAccessFeatures getSurveys getActiveMatchingSurveys renderSurvey canRenderSurvey captureException startSessionRecording stopSessionRecording sessionRecordingStarted capturePerformance captureTraceFeedback captureTraceMetric startExceptionCapture stopExceptionCapture".split(" "),n=0;n<o.length;n++)g(u,o[n]);e._i.push([i,s,a])},e.__SV=1)}(document,window.posthog||[]);posthog.init('phc_qXkp5FBQfrqHQwkqf3ys8iSoGoMYw2tpTHXGugXJhP8V',{api_host:'https://us.i.posthog.com',defaults:'2026-05-30',person_profiles:'identified_only',capture_pageview:true,capture_pageleave:true,autocapture:{dom_event_allowlist:['click'],element_allowlist:['a','button']},disable_session_recording:true,save_campaign_params:false,save_referrer:false,advanced_disable_flags:true,before_send:function(event){return window.dexpotSanitizeAnalyticsEvent?window.dexpotSanitizeAnalyticsEvent(event):event}});`;
