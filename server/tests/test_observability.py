from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock
from uuid import uuid4

import pytest
from opentelemetry.sdk.metrics.export import InMemoryMetricReader
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.api.v1.memory import LogMemoryRequest, log_memory
from app.middleware.context import RequestContext
from app.models import Embedding, Episode, Organization
from app.observability import reset_otel_state_for_tests, setup_otel
from app.services.embeddings import EmbeddingProvider, set_embedding_provider_override
from app.services.episodic import EpisodicMemory
from app.services.forgetting import ForgettingService
from app.services.scoping import MemoryScope

_SPAN_EXPORTER = InMemorySpanExporter()
_METRIC_READER = InMemoryMetricReader()


class _FakeEmbeddingProvider(EmbeddingProvider):
    @property
    def model(self) -> str:
        return "test-embedding-model"

    @property
    def dimensions(self) -> int | None:
        return 3

    async def generate_embedding(self, text: str) -> tuple[list[float], int]:
        return [0.1, 0.2, 0.3], 3

    async def generate_embeddings_batch(self, texts: list[str]) -> list[tuple[list[float], int]]:
        return [([0.1, 0.2, 0.3], 3) for _ in texts]


def _otel_settings(enabled: bool = True) -> SimpleNamespace:
    return SimpleNamespace(
        otel_enabled=enabled,
        otel_service_name="remembr-test",
        otel_exporter_endpoint=None,
        otel_traces_sample_rate=1.0,
        environment="local",
    )


def _metric_totals() -> dict[str, int]:
    data = _METRIC_READER.get_metrics_data()
    totals: dict[str, int] = {}
    for resource_metric in data.resource_metrics:
        for scope_metric in resource_metric.scope_metrics:
            for metric in scope_metric.metrics:
                if not hasattr(metric.data, "data_points"):
                    continue
                totals[metric.name] = sum(
                    int(getattr(point, "value", 0)) for point in metric.data.data_points
                )
    return totals


@pytest.fixture
def request_context() -> RequestContext:
    return RequestContext(
        request_id="req-otel",
        org_id=uuid4(),
        user_id=uuid4(),
        agent_id=None,
        auth_method="jwt",
    )


@pytest.fixture
def otel_enabled(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr("app.observability.otel.get_settings", lambda: _otel_settings())
    setup_otel(span_exporter=_SPAN_EXPORTER, metric_reader=_METRIC_READER)
    _SPAN_EXPORTER.clear()
    yield


@pytest.mark.asyncio
async def test_setup_otel_disabled_exports_nothing(monkeypatch: pytest.MonkeyPatch):
    reset_otel_state_for_tests()
    exporter = InMemorySpanExporter()
    reader = InMemoryMetricReader()
    monkeypatch.setattr("app.observability.otel.get_settings", lambda: _otel_settings(False))

    configured = setup_otel(span_exporter=exporter, metric_reader=reader)

    assert configured is False
    assert list(exporter.get_finished_spans()) == []


@pytest.mark.asyncio
@pytest.mark.integration
async def test_memory_search_span_has_expected_attributes(
    db: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
    otel_enabled,
):
    org = Organization(name=f"OTel Org {uuid4().hex[:8]}")
    db.add(org)
    await db.flush()

    episode = Episode(
        org_id=org.id,
        role="user",
        content="semantic observability test",
        tags=["otel"],
        metadata_={},
    )
    db.add(episode)
    await db.flush()
    db.add(
        Embedding(
            org_id=org.id,
            episode_id=episode.id,
            content=episode.content,
            model="test-embedding-model",
            dimensions=3,
            vector=[0.1, 0.2, 0.3],
        )
    )
    await db.commit()

    set_embedding_provider_override(_FakeEmbeddingProvider())
    try:
        episodic = EpisodicMemory(db=db)
        results = await episodic.search_semantic(
            scope=MemoryScope(org_id=str(org.id), level="org"),
            query="observability semantics",
            limit=3,
        )
    finally:
        set_embedding_provider_override(None)

    spans = _SPAN_EXPORTER.get_finished_spans()
    search_spans = [span for span in spans if span.name == "memory.search"]

    assert results
    assert search_spans
    assert search_spans[-1].attributes["mode"] == "semantic"
    assert search_spans[-1].attributes["limit"] == 3
    assert search_spans[-1].attributes["query_length"] == len("observability semantics")


@pytest.mark.asyncio
@pytest.mark.integration
async def test_metrics_increment_on_store_search_and_delete(
    db: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
    request_context: RequestContext,
    otel_enabled,
):
    before = _metric_totals()

    mock_db = AsyncMock()
    mock_redis = AsyncMock()
    episode_id = uuid4()
    stored_episode = SimpleNamespace(
        id=episode_id,
        session_id=None,
        created_at=datetime.now(UTC),
        org_id=request_context.org_id,
        role="user",
        content="stored memory",
        embedding_status="pending",
        tags=[],
    )
    mock_episodic = Mock()
    mock_episodic.log = AsyncMock(return_value=stored_episode)
    monkeypatch.setattr("app.api.v1.memory.EpisodicMemory", lambda db: mock_episodic)

    mock_short_term = Mock()
    mock_short_term.token_count.return_value = 2
    mock_short_term.add_message = AsyncMock()
    monkeypatch.setattr("app.api.v1.memory.ShortTermMemory", lambda cache, db: mock_short_term)
    monkeypatch.setattr("app.api.v1.memory.emit_event_safely", AsyncMock())

    await log_memory(
        LogMemoryRequest(role="user", content="stored memory"),
        request_context,
        mock_db,
        mock_redis,
    )

    org = Organization(name=f"Delete Org {uuid4().hex[:8]}")
    db.add(org)
    await db.flush()

    search_episode = Episode(
        org_id=org.id,
        role="user",
        content="search and delete target",
        tags=["otel"],
        metadata_={},
    )
    db.add(search_episode)
    await db.flush()
    db.add(
        Embedding(
            org_id=org.id,
            episode_id=search_episode.id,
            content=search_episode.content,
            model="test-embedding-model",
            dimensions=3,
            vector=[0.1, 0.2, 0.3],
        )
    )
    await db.commit()

    set_embedding_provider_override(_FakeEmbeddingProvider())
    try:
        episodic = EpisodicMemory(db=db)
        await episodic.search_semantic(
            scope=MemoryScope(org_id=str(org.id), level="org"),
            query="delete target",
            limit=5,
        )
    finally:
        set_embedding_provider_override(None)

    session_factory = async_sessionmaker(db.bind, class_=AsyncSession, expire_on_commit=False)
    async with session_factory() as delete_db:
        service = ForgettingService(db=delete_db, redis=AsyncMock())
        await service.delete_episode(
            episode_id=search_episode.id,
            scope=MemoryScope(org_id=str(org.id), level="org"),
            request_id="req-delete",
            actor_user_id=None,
        )

    after = _metric_totals()

    assert (
        after["remembr_memories_stored_total"] >= before.get("remembr_memories_stored_total", 0) + 1
    )
    assert after["remembr_searches_total"] >= before.get("remembr_searches_total", 0) + 1
