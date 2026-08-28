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
	redirects: {
		...apiRedirects,
		// pdoc has no page of its own at /api/ — its generated index is only a
		// meta refresh, and `npm run api` deletes it. Owning the route here means
		// it resolves in the dev server too, which does not serve directory
		// indexes out of public/.
		'/api': `${base}/api/redlines.html`,
	},
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
					// The abridged set is the documentation someone integrating the
					// library needs; the planning documents are context, not usage.
					promote: ['start/**', 'guides/**'],
					exclude: ['project/**'],
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
			sidebar: [
				{ label: 'Start here', items: [{ autogenerate: { directory: 'start' } }] },
				{ label: 'Guides', items: [{ autogenerate: { directory: 'guides' } }] },
				{
					label: 'Reference',
					items: [
						{
							// pdoc's own index forwards to redlines.html. Linking the
							// directory rather than the file matters: Starlight strips
							// a .html extension from sidebar links, which would point
							// this at a page that does not exist.
							label: 'API reference',
							link: '/api/',
							attrs: { target: '_blank' },
						},
					],
				},
				{
					// Generated from the repository by scripts/sync-docs.mjs.
					label: 'Project',
					items: [
						{ label: 'PRD', link: '/project/prd/' },
						{ label: 'Roadmap', link: '/project/roadmap/' },
						{ label: 'Contributing', link: '/project/contributing/' },
						{
							label: 'Decision records',
							collapsed: true,
							items: [{ autogenerate: { directory: 'project/adr' } }],
						},
					],
				},
			],
		}),
	],
});
