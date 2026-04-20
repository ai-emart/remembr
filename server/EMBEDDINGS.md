# Embeddings

Remembr is provider-agnostic for text embeddings. You choose a backend via `EMBEDDING_PROVIDER`; no API key is needed for the default (`sentence_transformers`).

## Quick start

```bash
# Default: local sentence-transformers (no API key, model downloaded on first use)
EMBEDDING_PROVIDER=sentence_transformers

# Jina AI
EMBEDDING_PROVIDER=jina
JINA_API_KEY=jina_...

# Ollama (self-hosted)
EMBEDDING_PROVIDER=ollama
OLLAMA_BASE_URL=http://localhost:11434
OLLAMA_EMBEDDING_MODEL=nomic-embed-text

# OpenAI
EMBEDDING_PROVIDER=openai
OPENAI_API_KEY=sk-...
OPENAI_EMBEDDING_MODEL=text-embedding-3-small
```

Copy `.env.example` to `.env` and uncomment the block for your provider.

## Installing provider dependencies

Core `requirements.txt` covers Jina and Ollama (both use `httpx`, which is already listed). For sentence-transformers or OpenAI install extras:

```bash
pip install -r requirements-embeddings.txt          # all extras
pip install sentence-transformers                    # only ST
pip install openai                                   # only OpenAI
```

## Provider comparison

| Provider              | API key? | Local? | Notes                              |
|-----------------------|----------|--------|------------------------------------|
| `sentence_transformers` | No     | Yes    | Default. Slow first load (model download). |
| `jina`                | Yes      | No     | High quality multilingual. Rate-limited on free tier. |
| `ollama`              | No       | Yes    | Requires Ollama server running locally. |
| `openai`              | Yes      | No     | `text-embedding-3-small` is fast and cheap. |

## Architecture

```
User text
    │
    ▼
EmbeddingProvider (ABC)
    ├── JinaEmbeddingProvider
    ├── OllamaEmbeddingProvider
    ├── SentenceTransformersProvider
    └── OpenAIEmbeddingProvider
    │
    ▼
get_embedding_provider()   ← singleton factory, reads EMBEDDING_PROVIDER
    │
    ▼
EpisodicMemory._provider   ← uses provider directly
    │
    ▼
PostgreSQL / pgvector       ← cosine similarity search via <=> operator
```

## Using in tests

```python
from app.services.embeddings import set_embedding_provider_override, EmbeddingProvider

class FakeProvider(EmbeddingProvider):
    @property
    def model(self): return "fake"
    @property
    def dimensions(self): return 3
    async def generate_embedding(self, text): return ([0.1, 0.2, 0.3], 3)
    async def generate_embeddings_batch(self, texts): return [([0.1, 0.2, 0.3], 3)] * len(texts)

@pytest.fixture(autouse=True)
def fake_embeddings():
    set_embedding_provider_override(FakeProvider())
    yield
    set_embedding_provider_override(None)
```

## pgvector and HNSW index

Vectors are stored in the `embeddings` table with an HNSW index on the `vector` column using cosine distance:

```sql
CREATE INDEX ix_embeddings_vector_cosine ON embeddings
    USING hnsw (vector vector_cosine_ops);
```

Similarity queries use `1 - (vector <=> query::vector)` — values close to 1.0 are most similar. The default score threshold is **0.7** for semantic search and **0.65** for hybrid search.

## Re-embedding with a new model

If you switch providers, existing embeddings will have a different dimensionality. Re-embed by running:

```python
texts = [emb.content for emb in existing_embeddings]
new_vectors = await provider.generate_embeddings_batch(texts)
for emb, (vec, dims) in zip(existing_embeddings, new_vectors):
    emb.vector = vec
    emb.dimensions = dims
    emb.model = provider.model
await db.commit()
```
