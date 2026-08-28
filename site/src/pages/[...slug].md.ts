import type { APIRoute } from 'astro';
import { getCollection } from 'astro:content';

// Serves every documentation page as plain markdown at `<page>.md`, so an agent
// can fetch the source text instead of scraping rendered HTML. Part of the
// machine surface of ADR-0027, alongside /llms.txt and the schemas.
export async function getStaticPaths() {
	const docs = await getCollection('docs');
	return docs
		.filter((entry) => entry.body && !entry.id.endsWith('index') && entry.id !== '')
		.map((entry) => ({ params: { slug: entry.id }, props: { entry } }));
}

export const GET: APIRoute = ({ props }) => {
	const { entry } = props as { entry: { body: string; data: { title: string } } };
	return new Response(`# ${entry.data.title}\n\n${entry.body.trim()}\n`, {
		headers: { 'Content-Type': 'text/markdown; charset=utf-8' },
	});
};
