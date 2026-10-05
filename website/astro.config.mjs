// @ts-check
import { defineConfig } from 'astro/config';
import sitemap from '@astrojs/sitemap';
import starlight from '@astrojs/starlight';

const structuredData = {
  '@context': 'https://schema.org',
  '@graph': [
    {
      '@type': 'SoftwareApplication',
      name: 'Dexpot',
      applicationCategory: 'DeveloperApplication',
      operatingSystem: 'Python 3.12 or later',
      description: 'A synchronous Python API framework with adaptive execution for standard GIL and free-threaded CPython.',
      url: 'https://dexpot.modepot.io/',
      codeRepository: 'https://github.com/tugrulguner/dexpot',
      installUrl: 'https://pypi.org/project/dexpot/',
      license: 'https://opensource.org/license/mit',
      isPartOf: { '@type': 'Organization', name: 'ModePot', url: 'https://modepot.io/' },
    },
    { '@type': 'WebSite', name: 'Dexpot documentation', url: 'https://dexpot.modepot.io/', inLanguage: 'en' },
  ],
};

export default defineConfig({
  vite: {
    preview: { strictPort: true },
  },
  site: 'https://dexpot.modepot.io',
  integrations: [
    sitemap(),
    starlight({
      title: 'dexpot',
      components: { Header: './src/components/Header.astro' },
      description: 'A synchronous Python API framework with adaptive GIL and free-threaded execution.',
      favicon: '/favicon.svg',
      logo: {
        src: './src/assets/dexpot-mark.svg',
      },
      customCss: ['./src/styles/custom.css'],
      lastUpdated: true,
      editLink: {
        baseUrl: 'https://github.com/tugrulguner/dexpot/edit/main/website/',
      },
      social: [
        { icon: 'github', label: 'GitHub', href: 'https://github.com/tugrulguner/dexpot' },
        { icon: 'discord', label: 'ModePot Discord', href: 'https://discord.gg/u3AANZr6RG' },
      ],
      sidebar: [
        { label: 'Start', items: [
          { label: 'Overview', slug: 'index' },
          { label: 'Quick start', slug: 'quick-start' },
          { label: 'Build guides', slug: 'build-guides' },
        ] },
        { label: 'Framework contract', items: [
          { label: 'Routes and handlers', slug: 'route-contract' },
          { label: 'Execution model', slug: 'execution-model' },
          { label: 'HTTP boundary', slug: 'http-boundary' },
          { label: 'Current boundaries', slug: 'current-boundaries' },
        ] },
        { label: 'Use dexpot', items: [
          { label: 'Runnable examples', slug: 'examples' },
          { label: 'Request workbench', slug: 'playground' },
          { label: 'Coding-agent context', slug: 'agent-context' },
          { label: 'Project README', slug: 'project/readme' },
          { label: 'Project roadmap', slug: 'project/roadmap' },
        ] },
        { label: 'ModePot', link: 'https://modepot.io/' },
      ],
      head: [
        { tag: 'script', attrs: {}, content: `!function(t,e){var o,n,p,r;e.__SV||(window.posthog=e,e._i=[],e.init=function(i,s,a){function g(t,e){var o=e.split(".");2==o.length&&(t=t[o[0]],e=o[1]),t[e]=function(){t.push([e].concat(Array.prototype.slice.call(arguments,0)))}}(p=t.createElement("script")).type="text/javascript",p.crossOrigin="anonymous",p.async=!0,p.src=s.api_host.replace(".i.posthog.com","-assets.i.posthog.com")+"/static/array.js",(r=t.getElementsByTagName("script")[0]).parentNode.insertBefore(p,r);var u=e;for(void 0!==a?u=e[a]=[]:a="posthog",u.people=u.people||[],u.toString=function(t){var e="posthog";return"posthog"!==a&&(e+="."+a),t||(e+=" (stub)"),e},u.people.toString=function(){return u.toString(1)+".people (stub)"},o="init capture identify alias people.set people.set_once people.unset reset opt_in_capturing opt_out_capturing has_opted_in_capturing has_opted_out_capturing clear_opt_in_out_capturing onFeatureFlags getFeatureFlag getFeatureFlagPayload isFeatureEnabled reloadFeatureFlags updateEarlyAccessFeatureEnrollment getEarlyAccessFeatures getSurveys getActiveMatchingSurveys renderSurvey canRenderSurvey captureException startSessionRecording stopSessionRecording sessionRecordingStarted capturePerformance captureTraceFeedback captureTraceMetric startExceptionCapture stopExceptionCapture".split(" "),n=0;n<o.length;n++)g(u,o[n]);e._i.push([i,s,a])},e.__SV=1)}(document,window.posthog||[]);posthog.init('phc_qXkp5FBQfrqHQwkqf3ys8iSoGoMYw2tpTHXGugXJhP8V',{api_host:'https://us.i.posthog.com',defaults:'2026-05-30',person_profiles:'identified_only',capture_pageview:true,capture_pageleave:true,autocapture:{dom_event_allowlist:['click'],element_allowlist:['a','button']},disable_session_recording:true});` },
        { tag: 'meta', attrs: { name: 'author', content: 'Tugrul Guner' } },
        { tag: 'meta', attrs: { name: 'robots', content: 'index, follow, max-image-preview:large' } },
        { tag: 'link', attrs: { rel: 'alternate', type: 'text/plain', href: '/llms.txt', title: 'Dexpot summary for AI agents' } },
        { tag: 'meta', attrs: { property: 'og:image', content: 'https://dexpot.modepot.io/social-card-v2.png' } },
        { tag: 'meta', attrs: { property: 'og:image:width', content: '1200' } },
        { tag: 'meta', attrs: { property: 'og:image:height', content: '630' } },
        { tag: 'meta', attrs: { property: 'og:image:alt', content: 'Dexpot: plain synchronous handlers with adaptive execution' } },
        { tag: 'meta', attrs: { name: 'twitter:card', content: 'summary_large_image' } },
        { tag: 'meta', attrs: { name: 'twitter:image', content: 'https://dexpot.modepot.io/social-card-v2.png' } },
        { tag: 'meta', attrs: { name: 'twitter:image:alt', content: 'Dexpot: plain synchronous handlers with adaptive execution' } },
        { tag: 'script', attrs: { type: 'application/ld+json' }, content: JSON.stringify(structuredData) },
      ],
    }),
  ],
});
