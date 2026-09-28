// @ts-check
import { defineConfig } from 'astro/config';
import sitemap from '@astrojs/sitemap';
import starlight from '@astrojs/starlight';

export default defineConfig({
  site: 'https://dexpot.modepot.io',
  integrations: [
    sitemap(),
    starlight({
      title: 'dexpot',
      description: 'A synchronous Python API framework with adaptive GIL and free-threaded execution.',
      favicon: '/favicon.svg',
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
        ] },
        { label: 'Framework contract', items: [
          { label: 'Routes and handlers', slug: 'route-contract' },
          { label: 'Execution model', slug: 'execution-model' },
          { label: 'HTTP boundary', slug: 'http-boundary' },
          { label: 'Current boundaries', slug: 'current-boundaries' },
        ] },
        { label: 'Use dexpot', items: [
          { label: 'Runnable examples', slug: 'examples' },
          { label: 'Coding-agent context', slug: 'agent-context' },
        ] },
      ],
      head: [
        { tag: 'meta', attrs: { name: 'author', content: 'Tugrul Guner' } },
        { tag: 'meta', attrs: { name: 'robots', content: 'index, follow, max-image-preview:large' } },
        { tag: 'link', attrs: { rel: 'alternate', type: 'text/plain', href: '/llms.txt', title: 'Dexpot summary for AI agents' } },
      ],
    }),
  ],
});
