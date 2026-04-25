# Embeddings

Embeddings power semantic and hybrid retrieval. In the default Docker setup, Remembr uses Ollama with `nomic-embed-text`.

## Lifecycle

1. `POST /memory` stores the episode immediately.
2. The response includes `embedding_status`.
3. A worker generates embeddings asynchronously.
4. Semantic and hybrid retrieval improve once the status becomes `ready`.

## Why `pending` matters

If you store and search in the same request cycle, a just-stored episode may not appear in semantic results yet. Keyword search can still surface it if the text matches.

## Providers

- Ollama by default for local and self-hosted setups
- Other providers can be configured at deployment time

