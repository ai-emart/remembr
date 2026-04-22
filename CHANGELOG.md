# Changelog

All notable changes to Remembr will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

---

## [1.0.0] - 2026-02-25

### 🎉 Production Release

First production-ready release with all 8 framework adapters fully tested and verified.

### Added

#### Core Platform
- FastAPI server with versioned API (`/api/v1`) and structured error envelopes
- Async SQLAlchemy with PostgreSQL + pgvector support for episodic memory
- Redis-backed short-term memory with checkpoint/restore support
- JWT + API key authentication with request-scoped context propagation
- Multi-tenant isolation with row-level security (RLS)
- Hybrid retrieval combining semantic search + metadata filtering
- Forgetting APIs for episode/session/user deletion (GDPR compliance)
- Rate limiting with Redis-backed sliding window algorithm
- Health check endpoints for monitoring and orchestration

#### SDKs
- **Python SDK** - Full async client with retry logic and error handling
- **TypeScript SDK** - Complete client for Node.js and browser environments
- Session management (create, list, get, checkpoint, restore)
- Memory operations (store, search, delete)
- Hybrid search with configurable filters
- Automatic token counting and metadata support

#### Framework Adapters (8/8 Production Ready ✅)
- **LangChain** - `BaseMemory` drop-in replacement for chains and agents
- **LangGraph** - Graph state integration with checkpointer support
- **CrewAI** - Shared crew memory for multi-agent collaboration
- **AutoGen** - Agent hook injection for ConversableAgent memory
- **LlamaIndex** - Chat store and semantic memory buffer for RAG
- **Pydantic AI** - Typed dependency injection for structured agents
- **OpenAI Agents** - Function tools for Swarm and handoff patterns
- **Haystack** - Pipeline components for RAG orchestration

All adapters verified with end-to-end tests achieving 100% pass rate.

#### Production Features
- Database connection pooling with configurable limits
- Structured logging with request IDs for traceability
- Error tracking integration (Sentry support)
- CORS configuration for web applications
- Environment-based configuration (dev/staging/prod)
- Alembic migrations for database schema management

### Documentation
- **README.md** - Professional overview with Mermaid architecture diagrams
- **ARCHITECTURE.md** - Deep technical architecture documentation
- **CONTRIBUTING.md** - Comprehensive contribution guidelines
- **DEPLOYMENT.md** - Multi-platform deployment guide (Railway, Docker, K8s)
- **Quickstart Guide** - 5-minute getting started (Python + TypeScript)
- **API Reference** - Complete REST API documentation with examples
- **Concepts Guide** - Memory layers, scoping, hybrid search, GDPR
- **Security Guide** - Authentication, authorization, compliance
- **Self-Hosted Setup** - Docker Compose and Kubernetes deployment
- **Adapter Guides** - Framework-specific integration docs (8 frameworks)

### Testing
- Unit tests with >80% coverage
- Integration tests for all API endpoints
- End-to-end tests for critical user flows
- Adapter tests verifying all 8 frameworks
- Performance benchmarks with Locust
- Security tests for authentication and authorization

### Infrastructure
- Railway deployment template with one-click setup
- Docker and Docker Compose configurations
- Kubernetes manifests for production deployment
- GitHub Actions CI/CD workflows
- Issue and PR templates for contributions

---

## [0.1.0] - 2026-02-01

### 🚀 MVP Release

Initial release with core functionality and adapter ecosystem.

### Added

#### Core Platform
- FastAPI server with versioned API (`/api/v1`)
- PostgreSQL + pgvector for episodic memory storage
- Redis for short-term memory caching
- JWT authentication with access and refresh tokens
- API key authentication for service-to-service
- Session management with metadata support
- Memory storage with automatic embedding generation
- Basic search functionality

#### SDKs
- Python SDK with async support
- TypeScript SDK for Node.js

#### Framework Adapters (Initial 8)
- LangChain adapter (beta)
- LangGraph adapter (beta)
- CrewAI adapter (beta)
- AutoGen adapter (beta)
- LlamaIndex adapter (beta)
- Pydantic AI adapter (beta)
- OpenAI Agents adapter (beta)
- Haystack adapter (beta)

#### Documentation
- Basic README with installation instructions
- API reference documentation
- Quickstart guide
- Concepts documentation

---

## [Unreleased]

### Planned Features
- Vector database support (Pinecone, Weaviate, Qdrant)
- Multi-modal memory (images, audio, video)
- Federated search across organizations
- Automatic memory compression and summarization
- Real-time sync with WebSocket support
- GraphQL API alternative
- Memory analytics and insights dashboard
- Advanced RBAC (Role-Based Access Control)
- Audit logging for compliance
- Memory versioning and history

---

## Version History

- **1.0.0** (2026-02-25) - Production release with all adapters tested
- **0.1.0** (2026-02-01) - MVP release with core functionality

---

## Migration Guides

### Upgrading from 0.1.0 to 1.0.0

#### Breaking Changes
- **LangChain Adapter**: Updated to use `langchain_core.memory.BaseMemory` instead of deprecated `langchain.memory.chat_memory.BaseChatMemory`
  - **Action Required**: Update imports if using LangChain 1.2.10+
  - Old: `from langchain.memory import BaseChatMemory`
  - New: `from langchain_core.memory import BaseMemory`

#### New Features
- All adapters now production-ready with full test coverage
- Enhanced error handling and retry logic in SDKs
- Improved rate limiting with Redis timeouts
- Better documentation and examples

#### Database Migrations
```bash
# Run migrations to update schema
alembic upgrade head
```

#### Configuration Changes
- Added `RATE_LIMIT_ENABLED` environment variable (default: `true`)
- Added `RATE_LIMIT_REQUESTS` environment variable (default: `1000`)
- Added `RATE_LIMIT_WINDOW` environment variable (default: `60`)

---

## Support

For questions or issues:
- **GitHub Issues**: [Report bugs or request features](https://github.com/ai-emart/remembr/issues)
- **Email**: [nwangumaemmanuel29@gmail.com](mailto:nwangumaemmanuel29@gmail.com)
- **Documentation**: [docs/](docs/)

---

**Maintained by**: [Emmanuel Nwanguma](https://linkedin.com/in/nwangumaemmanuel)  
**Repository**: [github.com/ai-emart/remembr](https://github.com/ai-emart/remembr)  
**License**: MIT
