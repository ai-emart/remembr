# Remembr TypeScript SDK

`@remembr/sdk` is the official TypeScript client for Remembr. It lets Node and TypeScript apps create sessions, store memories, search prior context, and manage export and forget flows against a self-hosted Remembr API.

## Install

```bash
npm install @remembr/sdk
```

## Quick Start

```typescript
import { RemembrClient } from '@remembr/sdk';

async function main() {
  const client = new RemembrClient({
    apiKey: process.env.REMEMBR_API_KEY!,
    baseUrl: 'http://localhost:8000/api/v1'
  });

  const session = await client.createSession({
    user: 'demo',
    context: 'support'
  });

  await client.store({
    content: 'User prefers dark mode interface',
    role: 'user',
    sessionId: session.session_id,
    tags: ['preference', 'ui']
  });

  const results = await client.search({
    query: 'What are the user UI preferences?',
    sessionId: session.session_id,
    limit: 5,
    searchMode: 'hybrid',
    weights: { semantic: 0.6, keyword: 0.3, recency: 0.1 }
  });

  results.results.forEach((memory) => {
    console.log(`[${memory.role}] ${memory.content} (score: ${memory.score})`);
  });
}

main();
```

## Docs

- Full docs: https://github.com/ai-emart/remembr/tree/main/docs
- Quick start: https://github.com/ai-emart/remembr#quick-start
- API reference: https://github.com/ai-emart/remembr/blob/main/docs/api-reference.md
