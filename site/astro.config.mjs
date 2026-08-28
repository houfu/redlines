// @ts-check
import { defineConfig } from 'astro/config';
import starlight from '@astrojs/starlight';
import starlightLlmsTxt from 'starlight-llms-txt';

// The site is published to GitHub Pages at https://houfu.github.io/redlines/,
// so every internal link has to carry the /redlines base.
const base = '/redlines';

// pdoc's HTML lands in public/api/ and is copied verbatim, so the API
// reference keeps its own layout and search. Before this site existed pdoc
// owned the site root; these keep the old deep links alive. See ADR-0026.
const apiRedirects = Object.fromEntries(
	['', '/cli', '/document', '/enums', '/pdf', '/processor', '/redlines'].map((mod) => [
		`/redlines${mod}.html`,
		`${base}/api/redlines${mod}.html`,
	])
);

export default defineConfig({
	site: 'https://houfu.github.io',
	base,
	redirects: apiRedirects,
	integrations: [
		starlight({
			title: 'redlines',
			description:
				'Compare text and produce human-readable differences that look like track changes.',
			social: [
				{ icon: 'github', label: 'GitHub', href: 'https://github.com/houfu/redlines' },
			],
			editLink: {
				baseUrl: 'https://github.com/houfu/redlines/edit/main/site/',
			},
			// Publishes /llms.txt and per-page markdown, so an agent can fetch the
			// documentation as text rather than scraping HTML. See ADR-0027.
			plugins: [
				starlightLlmsTxt({
					projectName: 'redlines',
					description:
						'A Python library and CLI that compares two texts and reports the differences as markdown, rich text or JSON.',
					optionalLinks: [
						{
							label: 'API reference (pdoc)',
							url: 'https://houfu.github.io/redlines/api/redlines.html',
							description: 'Generated from docstrings; the source of truth for the API.',
						},
					],
				}),
			],
			// The prose pages arrive with the content migration; the API
			// reference is here from the first deploy.
			sidebar: [
				{
					label: 'Reference',
					items: [
						{
							label: 'API reference',
							link: '/api/redlines.html',
							attrs: { target: '_blank' },
						},
					],
				},
			],
		}),
	],
});
