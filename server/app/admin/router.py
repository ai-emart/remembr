"""Dev-only admin UI served at /admin — localhost only, no auth."""
from __future__ import annotations

import uuid
from pathlib import Path
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import desc, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_db
from app.models.episode import Episode
from app.models.organization import Organization
from app.models.session import Session

_HERE = Path(__file__).parent
_TEMPLATES = Jinja2Templates(directory=str(_HERE / "templates"))

_LOCALHOST = {"127.0.0.1", "::1", "localhost", "testclient"}

router = APIRouter(prefix="/admin", tags=["admin"])


# ---------------------------------------------------------------------------
# Localhost guard
# ---------------------------------------------------------------------------

def _guard(request: Request) -> None:
    host = request.client.host if request.client else ""
    if host not in _LOCALHOST:
        raise HTTPException(status_code=403, detail="Admin UI is only accessible from localhost")


_LocalhostGuard = Annotated[None, Depends(_guard)]


# ---------------------------------------------------------------------------
# Org resolution
# ---------------------------------------------------------------------------

async def _resolve_org_id(request: Request, db: AsyncSession) -> uuid.UUID:
    header = request.headers.get("X-Admin-Org-ID", "").strip()
    if header:
        try:
            return uuid.UUID(header)
        except ValueError:
            pass
    result = await db.execute(select(Organization).limit(1))
    org = result.scalar_one_or_none()
    if org is None:
        raise HTTPException(status_code=404, detail="No organizations found in database")
    return org.id


# ---------------------------------------------------------------------------
# DB helpers
# ---------------------------------------------------------------------------

async def _list_sessions(
    db: AsyncSession,
    org_id: uuid.UUID,
    limit: int = 20,
    offset: int = 0,
) -> list[dict[str, Any]]:
    q = (
        select(
            Session,
            func.count(Episode.id).label("message_count"),
            func.max(Episode.created_at).label("last_activity"),
        )
        .outerjoin(
            Episode,
            (Episode.session_id == Session.id) & Episode.deleted_at.is_(None),
        )
        .where(Session.org_id == org_id)
        .where(Session.deleted_at.is_(None))
        .group_by(Session.id)
        .order_by(desc(Session.updated_at))
        .limit(limit)
        .offset(offset)
    )
    rows = (await db.execute(q)).all()
    return [
        {
            "id": str(r.Session.id),
            "created_at": r.Session.created_at,
            "updated_at": r.Session.updated_at,
            "message_count": r.message_count or 0,
            "last_activity": r.last_activity,
            "metadata": r.Session.metadata_ or {},
        }
        for r in rows
    ]


async def _count_sessions(db: AsyncSession, org_id: uuid.UUID) -> int:
    result = await db.execute(
        select(func.count(Session.id))
        .where(Session.org_id == org_id)
        .where(Session.deleted_at.is_(None))
    )
    return int(result.scalar_one())


async def _list_episodes(
    db: AsyncSession,
    org_id: uuid.UUID,
    session_id: uuid.UUID,
    limit: int = 20,
    offset: int = 0,
) -> list[dict[str, Any]]:
    q = (
        select(Episode)
        .where(Episode.session_id == session_id)
        .where(Episode.org_id == org_id)
        .where(Episode.deleted_at.is_(None))
        .order_by(Episode.created_at.asc())
        .limit(limit)
        .offset(offset)
    )
    episodes = (await db.execute(q)).scalars().all()
    return [
        {
            "id": str(ep.id),
            "role": ep.role,
            "content": ep.content,
            "tags": ep.tags or [],
            "created_at": ep.created_at,
            "embedding_status": ep.embedding_status,
        }
        for ep in episodes
    ]


async def _search_episodes(
    db: AsyncSession,
    org_id: uuid.UUID,
    query: str,
    session_id: str | None,
    tags: str | None,
    limit: int = 30,
) -> list[dict[str, Any]]:
    q = (
        select(Episode)
        .where(Episode.org_id == org_id)
        .where(Episode.deleted_at.is_(None))
        .where(Episode.content.ilike(f"%{query}%"))
    )
    if session_id:
        try:
            q = q.where(Episode.session_id == uuid.UUID(session_id))
        except ValueError:
            pass
    if tags:
        tag_list = [t.strip() for t in tags.split(",") if t.strip()]
        if tag_list:
            q = q.where(Episode.tags.op("&&")(tag_list))
    q = q.order_by(desc(Episode.created_at)).limit(limit)
    episodes = (await db.execute(q)).scalars().all()
    return [
        {
            "id": str(ep.id),
            "session_id": str(ep.session_id) if ep.session_id else None,
            "role": ep.role,
            "content": ep.content,
            "tags": ep.tags or [],
            "created_at": ep.created_at,
        }
        for ep in episodes
    ]


async def _get_health_data(db: AsyncSession) -> dict[str, Any]:
    from app.config import get_settings

    settings = get_settings()

    pg_ok, pg_error = False, ""
    try:
        await db.execute(select(func.now()))
        pg_ok = True
    except Exception as exc:
        pg_error = str(exc)

    redis_ok, redis_error = False, ""
    try:
        from app.db.redis import get_redis_client

        redis = get_redis_client()
        await redis.ping()
        redis_ok = True
    except Exception as exc:
        redis_error = str(exc)

    return {
        "pg_ok": pg_ok,
        "pg_error": pg_error,
        "redis_ok": redis_ok,
        "redis_error": redis_error,
        "embedding_provider": settings.embedding_provider,
        "environment": settings.environment,
    }


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

_PER_PAGE = 20


@router.get("/", response_class=HTMLResponse)
@router.get("", response_class=HTMLResponse)
async def admin_index(
    request: Request,
    _: _LocalhostGuard,
    db: AsyncSession = Depends(get_db),
) -> HTMLResponse:
    org_id = await _resolve_org_id(request, db)
    sessions = await _list_sessions(db, org_id, limit=_PER_PAGE)
    total = await _count_sessions(db, org_id)
    return _TEMPLATES.TemplateResponse(
        "sessions.html",
        {
            "request": request,
            "sessions": sessions,
            "total": total,
            "page": 1,
            "per_page": _PER_PAGE,
            "org_id": str(org_id),
        },
    )


@router.get("/sessions", response_class=HTMLResponse)
async def sessions_list(
    request: Request,
    _: _LocalhostGuard,
    db: AsyncSession = Depends(get_db),
    page: int = 1,
) -> HTMLResponse:
    org_id = await _resolve_org_id(request, db)
    offset = (page - 1) * _PER_PAGE
    sessions = await _list_sessions(db, org_id, limit=_PER_PAGE, offset=offset)
    total = await _count_sessions(db, org_id)
    return _TEMPLATES.TemplateResponse(
        "sessions.html",
        {
            "request": request,
            "sessions": sessions,
            "total": total,
            "page": page,
            "per_page": _PER_PAGE,
            "org_id": str(org_id),
        },
    )


@router.get("/sessions/{session_id}", response_class=HTMLResponse)
async def session_detail(
    request: Request,
    session_id: str,
    _: _LocalhostGuard,
    db: AsyncSession = Depends(get_db),
) -> HTMLResponse:
    org_id = await _resolve_org_id(request, db)
    try:
        sid = uuid.UUID(session_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid session ID")
    episodes = await _list_episodes(db, org_id, sid, limit=_PER_PAGE)
    return _TEMPLATES.TemplateResponse(
        "memories.html",
        {
            "request": request,
            "session_id": session_id,
            "episodes": episodes,
            "next_offset": _PER_PAGE,
            "has_more": len(episodes) == _PER_PAGE,
        },
    )


@router.get("/sessions/{session_id}/memories", response_class=HTMLResponse)
async def memories_more(
    request: Request,
    session_id: str,
    _: _LocalhostGuard,
    db: AsyncSession = Depends(get_db),
    offset: int = 0,
) -> HTMLResponse:
    org_id = await _resolve_org_id(request, db)
    try:
        sid = uuid.UUID(session_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid session ID")
    episodes = await _list_episodes(db, org_id, sid, limit=_PER_PAGE, offset=offset)
    return _TEMPLATES.TemplateResponse(
        "_memory_rows.html",
        {
            "request": request,
            "session_id": session_id,
            "episodes": episodes,
            "next_offset": offset + len(episodes),
            "has_more": len(episodes) == _PER_PAGE,
        },
    )


@router.get("/search", response_class=HTMLResponse)
async def search_page(
    request: Request,
    _: _LocalhostGuard,
    db: AsyncSession = Depends(get_db),
) -> HTMLResponse:
    org_id = await _resolve_org_id(request, db)
    sessions = await _list_sessions(db, org_id, limit=200)
    return _TEMPLATES.TemplateResponse(
        "search.html",
        {
            "request": request,
            "sessions": sessions,
            "org_id": str(org_id),
            "results": [],
            "query": "",
        },
    )


@router.post("/search", response_class=HTMLResponse)
async def search_submit(
    request: Request,
    _: _LocalhostGuard,
    db: AsyncSession = Depends(get_db),
    query: str = Form(default=""),
    session_filter: str = Form(default=""),
    tag_filter: str = Form(default=""),
) -> HTMLResponse:
    org_id = await _resolve_org_id(request, db)
    results: list[dict[str, Any]] = []
    if query.strip():
        results = await _search_episodes(
            db, org_id, query.strip(), session_filter or None, tag_filter or None
        )
    return _TEMPLATES.TemplateResponse(
        "_search_results.html",
        {"request": request, "results": results, "query": query},
    )


@router.get("/health", response_class=HTMLResponse)
async def health_page(
    request: Request,
    _: _LocalhostGuard,
    db: AsyncSession = Depends(get_db),
) -> HTMLResponse:
    data = await _get_health_data(db)
    is_htmx = "hx-request" in request.headers
    template = "_health_cards.html" if is_htmx else "health.html"
    return _TEMPLATES.TemplateResponse(template, {"request": request, **data})
