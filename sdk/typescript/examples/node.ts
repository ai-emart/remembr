import { RemembrClient } from '../src';

async function run(): Promise<void> {
  const client = new RemembrClient({ apiKey: process.env.REMEMBR_API_KEY });

  const session = await client.createSession({ source: 'node-example' });
  await client.store({ content: 'Hello from Node.js', sessionId: session.session_id, tags: ['example'] });

  const results = await client.search({
    query: 'Hello',
    sessionId: session.session_id,
    limit: 5,
    searchMode: 'hybrid',
    weights: { semantic: 0.6, keyword: 0.3, recency: 0.1 },
  });
  console.log(results.total, results.results.map((r) => r.content));
}

void run();
