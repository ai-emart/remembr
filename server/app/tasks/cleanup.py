"""Celery periodic tasks for database cleanup."""

from __future__ import annotations

import asyncio
import concurrent.futures
from datetime import UTC, datetime, timedelta

from loguru import logger

from app.celery_app import celery_app
from app.db.session import AsyncSessionLocal

SOFT_DELETE_GRACE_DAYS = 30


def _run_async(coro):
    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as executor:
        return executor.submit(asyncio.run, coro).result()


async def _do_purge_soft_deleted() -> dict:
    """Hard-delete rows where deleted_at < now() - 30 days."""
    from sqlalchemy import delete

    from app.models import Embedding, Episode, Session

    cutoff = datetime.now(UTC) - timedelta(days=SOFT_DELETE_GRACE_DAYS)
    results: dict[str, int] = {}

    async with AsyncSessionLocal() as db:
        async with db.begin():
            emb_result = await db.execute(
                delete(Embedding).where(Embedding.deleted_at < cutoff)
            )
            results["embeddings"] = emb_result.rowcount

            ep_result = await db.execute(
                delete(Episode).where(Episode.deleted_at < cutoff)
            )
            results["episodes"] = ep_result.rowcount

            sess_result = await db.execute(
                delete(Session).where(Session.deleted_at < cutoff)
            )
            results["sessions"] = sess_result.rowcount

    logger.info(
        "Purge completed",
        cutoff=cutoff.isoformat(),
        purged_embeddings=results["embeddings"],
        purged_episodes=results["episodes"],
        purged_sessions=results["sessions"],
    )
    return results


@celery_app.task(name="app.tasks.cleanup.purge_soft_deleted")
def purge_soft_deleted() -> dict:
    """Daily hard-delete of expired soft-deleted rows (older than 30 days).

    Scheduled via Celery Beat to run at 03:00 UTC every day.
    """
    return _run_async(_do_purge_soft_deleted())
