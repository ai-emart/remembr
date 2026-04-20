"""Data-portability export endpoint.

GET /api/v1/export streams episodes for the authenticated scope as either a
JSON array or a CSV document without buffering the full dataset in memory.

Query parameters:
  format          json | csv          (default: json)
  from_date       ISO 8601 date       (optional)
  to_date         ISO 8601 date       (optional)
  session_id      UUID                (optional)
  include_deleted true | false        (default: false)
"""

from __future__ import annotations

import csv
import io
import json
from datetime import datetime
from typing import Annotated, AsyncGenerator
from uuid import UUID

from fastapi import APIRouter, Depends, Query
from fastapi.responses import StreamingResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_db
from app.middleware.context import RequestContext, require_auth
from app.models import Episode
from app.services.scoping import MemoryScope, ScopeResolver

router = APIRouter(tags=["export"])

_BATCH_SIZE = 100


def _ep_to_dict(ep: Episode) -> dict:
    return {
        "id": str(ep.id),
        "session_id": str(ep.session_id) if ep.session_id else None,
        "role": ep.role,
        "content": ep.content,
        "tags": ep.tags or [],
        "metadata": ep.metadata_ or {},
        "created_at": ep.created_at.isoformat() if ep.created_at else None,
        "embedding_status": ep.embedding_status,
    }


async def _iter_episodes(
    db: AsyncSession,
    scope: MemoryScope,
    from_date: datetime | None,
    to_date: datetime | None,
    session_id: UUID | None,
    include_deleted: bool,
) -> AsyncGenerator[Episode, None]:
    """Yield episodes in batches of _BATCH_SIZE to avoid loading the full set in memory."""
    offset = 0
    while True:
        query = (
            select(Episode)
            .where(Episode.org_id == UUID(scope.org_id))
            .where(Episode.team_id == (UUID(scope.team_id) if scope.team_id else None))
            .where(Episode.user_id == (UUID(scope.user_id) if scope.user_id else None))
            .where(Episode.agent_id == (UUID(scope.agent_id) if scope.agent_id else None))
            .order_by(Episode.created_at.asc())
            .limit(_BATCH_SIZE)
            .offset(offset)
        )

        if not include_deleted:
            query = query.where(Episode.not_deleted())
        if from_date:
            query = query.where(Episode.created_at >= from_date)
        if to_date:
            query = query.where(Episode.created_at <= to_date)
        if session_id:
            query = query.where(Episode.session_id == session_id)

        result = await db.execute(query)
        batch = list(result.scalars().all())

        for ep in batch:
            yield ep

        if len(batch) < _BATCH_SIZE:
            break
        offset += _BATCH_SIZE


async def _stream_json(
    db: AsyncSession,
    scope: MemoryScope,
    from_date: datetime | None,
    to_date: datetime | None,
    session_id: UUID | None,
    include_deleted: bool,
) -> AsyncGenerator[bytes, None]:
    yield b"["
    first = True
    async for ep in _iter_episodes(db, scope, from_date, to_date, session_id, include_deleted):
        if not first:
            yield b","
        yield json.dumps(_ep_to_dict(ep)).encode()
        first = False
    yield b"]"


async def _stream_csv(
    db: AsyncSession,
    scope: MemoryScope,
    from_date: datetime | None,
    to_date: datetime | None,
    session_id: UUID | None,
    include_deleted: bool,
) -> AsyncGenerator[bytes, None]:
    fieldnames = ["id", "session_id", "role", "content", "tags", "metadata", "created_at", "embedding_status"]
    buf = io.StringIO()
    writer = csv.DictWriter(buf, fieldnames=fieldnames, lineterminator="\n")
    writer.writeheader()
    yield buf.getvalue().encode()

    async for ep in _iter_episodes(db, scope, from_date, to_date, session_id, include_deleted):
        row = _ep_to_dict(ep)
        row["tags"] = ";".join(row["tags"])
        row["metadata"] = json.dumps(row["metadata"])
        buf = io.StringIO()
        writer = csv.DictWriter(buf, fieldnames=fieldnames, lineterminator="\n")
        writer.writerow(row)
        yield buf.getvalue().encode()


@router.get("/export")
async def export_memory(
    ctx: Annotated[RequestContext, Depends(require_auth)],
    db: Annotated[AsyncSession, Depends(get_db)],
    format: str = Query("json", pattern="^(json|csv)$"),
    from_date: datetime | None = Query(None),
    to_date: datetime | None = Query(None),
    session_id: UUID | None = Query(None),
    include_deleted: bool = Query(False),
) -> StreamingResponse:
    """Stream all episodes for the authenticated scope.

    - **format**: `json` (default) returns a JSON array; `csv` returns CSV with headers.
    - **from_date / to_date**: ISO 8601 timestamps to bound the export window.
    - **session_id**: Limit export to a single session.
    - **include_deleted**: Include soft-deleted episodes (default: false).
    """
    scope = ScopeResolver.resolve_writable_scope(ScopeResolver.from_request_context(ctx))
    sid = session_id

    if format == "csv":
        filename = "remembr_export.csv"
        media_type = "text/csv"
        gen = _stream_csv(db, scope, from_date, to_date, sid, include_deleted)
    else:
        filename = "remembr_export.json"
        media_type = "application/json"
        gen = _stream_json(db, scope, from_date, to_date, sid, include_deleted)

    return StreamingResponse(
        gen,
        media_type=media_type,
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
