from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import text

from app.models import Embedding, Episode, Organization, User
from app.services.embeddings import EmbeddingProvider, set_embedding_provider_override
from app.services.episodic import EpisodicMemory
from app.services.scoping import MemoryScope
from app.services.search_config import SearchWeights


@dataclass(frozen=True)
class _Scenario:
    query: str
    expected_episode_id: str


class _MappedProvider(EmbeddingProvider):
    def __init__(self, vectors: dict[str, list[float]]) -> None:
        self._vectors = vectors

    @property
    def model(self) -> str:
        return "test-model"

    @property
    def dimensions(self) -> int | None:
        return 3

    async def generate_embedding(self, text: str) -> tuple[list[float], int]:
        vector = self._vectors[text]
        return vector, len(vector)

    async def generate_embeddings_batch(self, texts: list[str]) -> list[tuple[list[float], int]]:
        return [await self.generate_embedding(text) for text in texts]


@pytest.fixture(autouse=True)
def _reset_provider() -> None:
    yield
    set_embedding_provider_override(None)


async def _add_episode(
    db,
    *,
    org_id: uuid.UUID,
    content: str,
    created_at: datetime,
    vector: list[float],
) -> Episode:
    episode = Episode(
        org_id=org_id,
        role="user",
        content=content,
        tags=[],
        metadata_={},
        created_at=created_at,
    )
    db.add(episode)
    await db.flush()
    db.add(
        Embedding(
            org_id=org_id,
            episode_id=episode.id,
            content=content,
            model="test-model",
            dimensions=len(vector),
            vector=vector,
        )
    )
    await db.flush()
    return episode


async def _refresh_search_vectors(db) -> None:
    await db.execute(
        text("UPDATE episodes SET search_vector = to_tsvector('english', COALESCE(content, ''))")
    )
    await db.commit()


@pytest.mark.asyncio
async def test_search_weights_model_rejects_invalid_total():
    with pytest.raises(ValueError, match="must sum to 1.0"):
        SearchWeights(semantic=0.5, keyword=0.4, recency=0.2)


@pytest.mark.asyncio
async def test_invalid_weights_return_400(client, db):
    from app.services.auth import create_access_token

    org = Organization(name="Search Weights Org")
    db.add(org)
    await db.flush()
    user = User(
        org_id=org.id,
        email=f"search-{uuid.uuid4().hex[:8]}@example.com",
        hashed_password="hashed",
        is_active=True,
    )
    db.add(user)
    await db.commit()

    token = create_access_token({"sub": str(user.id)})
    response = await client.post(
        "/api/v1/memory/search",
        headers={"Authorization": f"Bearer {token}"},
        json={
            "query": "billing",
            "search_mode": "hybrid",
            "weights": {"semantic": 0.5, "keyword": 0.4, "recency": 0.2},
        },
    )

    assert response.status_code == 400


@pytest.mark.asyncio
async def test_search_modes_cover_keyword_semantic_hybrid_and_recency(db):
    org = Organization(name="Search Fixture Org")
    db.add(org)
    await db.flush()

    now = datetime.now(UTC)
    vectors = {
        "ERR_1234": [-1.0, 0.0, 0.0],
        "ZX-9000": [0.0, -1.0, 0.0],
        "help me sign in again": [0.0, 0.0, 1.0],
        "plant based protein sauce": [0.0, 0.6, 0.8],
        "recent billing close issue ERR_5501": [0.8, 0.6, 0.0],
        "recent support ranking": [0.5, 0.5, 0.7],
    }
    set_embedding_provider_override(_MappedProvider(vectors))

    keyword_err = await _add_episode(
        db,
        org_id=org.id,
        content="Pager fired with error code ERR_1234 during checkout.",
        created_at=now - timedelta(days=3),
        vector=[0.0, 1.0, 0.0],
    )
    keyword_sku = await _add_episode(
        db,
        org_id=org.id,
        content="Warehouse note: SKU ZX-9000 needs a manual recount.",
        created_at=now - timedelta(days=2),
        vector=[1.0, 0.0, 0.0],
    )
    semantic_login = await _add_episode(
        db,
        org_id=org.id,
        content="Identity verification unlocks access for locked profiles.",
        created_at=now - timedelta(days=2),
        vector=[0.0, 0.0, 1.0],
    )
    semantic_tofu = await _add_episode(
        db,
        org_id=org.id,
        content="Whisk miso, tamari, and ginger for tofu marinade.",
        created_at=now - timedelta(days=1),
        vector=[0.0, 0.6, 0.8],
    )
    hybrid_old = await _add_episode(
        db,
        org_id=org.id,
        content="Legacy invoice job failed with ERR_5501 during nightly close.",
        created_at=now - timedelta(days=30),
        vector=[0.2, 0.0, 0.0],
    )
    hybrid_recent = await _add_episode(
        db,
        org_id=org.id,
        content="Finance alert: the billing batch stalled while closing books.",
        created_at=now - timedelta(hours=6),
        vector=[0.8, 0.6, 0.0],
    )
    recent_good = await _add_episode(
        db,
        org_id=org.id,
        content="Recent support summary: account recovery flow slowed but still worked.",
        created_at=now - timedelta(hours=2),
        vector=[0.5, 0.5, 0.7],
    )
    old_perfect = await _add_episode(
        db,
        org_id=org.id,
        content="Recent support ranking exact phrase stored long ago.",
        created_at=now - timedelta(days=45),
        vector=[0.2, 0.2, 0.2],
    )

    distractor_vectors = [
        [0.3, 0.1, 0.2],
        [0.2, 0.3, 0.1],
        [0.1, 0.2, 0.3],
        [0.4, 0.1, 0.1],
        [0.1, 0.4, 0.1],
        [0.1, 0.1, 0.4],
        [0.3, 0.3, 0.1],
        [0.3, 0.1, 0.3],
        [0.1, 0.3, 0.3],
        [0.25, 0.25, 0.15],
        [0.15, 0.25, 0.25],
        [0.25, 0.15, 0.25],
    ]
    distractor_texts = [
        "Customer asked for tax receipt resend.",
        "Notebook order waiting for courier pickup.",
        "Reminder to renew staging SSL certificate.",
        "Weekly standup notes captured for product team.",
        "A supplier delay affected paper packaging stock.",
        "Team lunch reservation moved to Thursday noon.",
        "Guide for exporting monthly analytics snapshots.",
        "Discussion about rotating on-call schedules fairly.",
        "Shipping webhook retried after timeout warning.",
        "Notes on enabling beta flags for new dashboard.",
        "Travel reimbursement policy updated for contractors.",
        "Prompt template for summarizing agent handoffs.",
    ]
    for content, vector in zip(distractor_texts, distractor_vectors, strict=True):
        await _add_episode(
            db,
            org_id=org.id,
            content=content,
            created_at=now - timedelta(days=5),
            vector=vector,
        )

    await _refresh_search_vectors(db)

    scope = MemoryScope(org_id=str(org.id), level="org")
    memory = EpisodicMemory(db=db)

    keyword_hits = await memory.search_keyword(scope=scope, query="ERR_1234", limit=5)
    assert keyword_hits[0].episode.id == keyword_err.id

    semantic_for_err = await memory.search_semantic(
        scope=scope,
        query="ERR_1234",
        limit=5,
        score_threshold=0.65,
    )
    assert all(result.episode.id != keyword_err.id for result in semantic_for_err)

    semantic_hits = await memory.search_semantic(
        scope=scope,
        query="help me sign in again",
        limit=5,
        score_threshold=0.65,
    )
    assert semantic_hits[0].episode.id == semantic_login.id

    keyword_for_paraphrase = await memory.search_keyword(
        scope=scope,
        query="help me sign in again",
        limit=5,
    )
    assert keyword_for_paraphrase == []

    scenarios = [
        _Scenario(query="ERR_1234", expected_episode_id=str(keyword_err.id)),
        _Scenario(query="ZX-9000", expected_episode_id=str(keyword_sku.id)),
        _Scenario(query="help me sign in again", expected_episode_id=str(semantic_login.id)),
        _Scenario(query="plant based protein sauce", expected_episode_id=str(semantic_tofu.id)),
        _Scenario(
            query="recent billing close issue ERR_5501", expected_episode_id=str(hybrid_recent.id)
        ),
    ]

    hybrid_hits = 0
    semantic_hits_count = 0
    keyword_hits_count = 0
    for scenario in scenarios:
        hybrid = await memory.search_hybrid(scope=scope, query=scenario.query, limit=5)
        semantic = await memory.search_semantic(
            scope=scope,
            query=scenario.query,
            limit=5,
            score_threshold=0.65,
        )
        keyword = await memory.search_keyword(scope=scope, query=scenario.query, limit=5)

        hybrid_hits += int(
            bool(hybrid) and str(hybrid[0].episode.id) == scenario.expected_episode_id
        )
        semantic_hits_count += int(
            bool(semantic) and str(semantic[0].episode.id) == scenario.expected_episode_id
        )
        keyword_hits_count += int(
            bool(keyword) and str(keyword[0].episode.id) == scenario.expected_episode_id
        )

    assert hybrid_hits == 5
    assert hybrid_hits > semantic_hits_count
    assert hybrid_hits > keyword_hits_count

    recency_heavy = await memory.search_hybrid(
        scope=scope,
        query="recent support ranking",
        limit=5,
        weights=SearchWeights(semantic=0.1, keyword=0.1, recency=0.8),
    )
    keyword_ranking = await memory.search_keyword(
        scope=scope, query="recent support ranking", limit=5
    )

    assert recency_heavy[0].episode.id == recent_good.id
    assert keyword_ranking[0].episode.id == old_perfect.id
    assert any(
        item.episode.id == hybrid_old.id
        for item in await memory.search_keyword(scope=scope, query="ERR_5501", limit=5)
    )
