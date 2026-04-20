"""Celery tasks for embedding generation."""

from __future__ import annotations

import asyncio
import concurrent.futures
from datetime import UTC, datetime

from loguru import logger

from app.celery_app import celery_app
from app.db.session import AsyncSessionLocal


def _run_async(coro):
    """Run a coroutine in a dedicated thread with its own event loop.

    Using a fresh thread avoids the 'event loop already running' error when
    the task executes eagerly inside a pytest-asyncio test suite.
    """
    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as executor:
        return executor.submit(asyncio.run, coro).result()


async def _do_generate_embedding(episode_id: str) -> None:
    """Fetch episode, generate embedding, persist, update status → 'ready'."""
    from sqlalchemy import select

    from app.models import Embedding, Episode
    from app.services.embeddings import get_embedding_provider

    provider = get_embedding_provider()

    async with AsyncSessionLocal() as db:
        episode = await db.get(Episode, episode_id)
        if episode is None:
            logger.warning("Skipping embedding: episode not found", episode_id=episode_id)
            return

        vector, dimensions = await provider.generate_embedding(episode.content)

        result = await db.execute(
            select(Embedding).where(Embedding.episode_id == episode.id)
        )
        existing = result.scalar_one_or_none()

        if existing:
            existing.vector = vector
            existing.dimensions = dimensions
            existing.model = provider.model
            existing.content = episode.content
        else:
            db.add(
                Embedding(
                    org_id=episode.org_id,
                    episode_id=episode.id,
                    content=episode.content,
                    model=provider.model,
                    dimensions=dimensions,
                    vector=vector,
                )
            )

        episode.embedding_status = "ready"
        episode.embedding_generated_at = datetime.now(UTC)
        episode.embedding_error = None

        await db.commit()
        logger.debug("Embedding stored", episode_id=episode_id, dims=dimensions)


async def _mark_failed(episode_id: str, error_msg: str) -> None:
    """Update episode embedding_status to 'failed' after all retries exhausted."""
    from app.models import Episode

    async with AsyncSessionLocal() as db:
        episode = await db.get(Episode, episode_id)
        if episode is not None:
            episode.embedding_status = "failed"
            episode.embedding_error = error_msg
            await db.commit()

    logger.error("Embedding permanently failed", episode_id=episode_id, error=error_msg)


@celery_app.task(
    bind=True,
    name="app.tasks.embeddings.generate_embedding_for_episode",
    max_retries=3,
)
def generate_embedding_for_episode(self, episode_id: str) -> None:
    """Generate and store an embedding for the given episode.

    Retries up to 3 times with exponential backoff. On permanent failure,
    sets embedding_status='failed' and records the error message.
    """
    try:
        _run_async(_do_generate_embedding(episode_id))
    except Exception as exc:
        is_final = self.request.retries >= self.max_retries
        if is_final:
            try:
                _run_async(_mark_failed(episode_id, repr(exc)[:500]))
            except Exception:
                logger.exception(
                    "Could not record embedding failure in DB", episode_id=episode_id
                )
        else:
            countdown = 2 ** self.request.retries
            raise self.retry(exc=exc, countdown=countdown)
