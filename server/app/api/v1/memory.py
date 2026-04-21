"""Memory and session management endpoints."""

from datetime import UTC, datetime
from time import perf_counter
from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Request, Response, status
from pydantic import BaseModel, Field
from redis.asyncio import Redis
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.responses import StandardResponse, success
from app.db.redis import get_redis
from app.db.session import get_db
from app.error_codes import (
    CHECKPOINT_NOT_FOUND,
    EPISODE_NOT_FOUND,
    INVALID_TIME_RANGE,
    ORG_LEVEL_REQUIRED,
    SESSION_NOT_FOUND,
)
from app.exceptions import AuthorizationError, NotFoundError, ValidationError
from app.middleware.context import RequestContext, require_auth
from app.middleware.rate_limit import get_search_limit, limiter
from app.models import Episode, Session
from app.services.cache import CacheService
from app.services.episodic import EpisodicMemory
from app.services.forgetting import ForgettingService
from app.services.scoping import MemoryScope, ScopeResolver
from app.services.short_term import SessionMessage, ShortTermMemory
from app.services.tag_filter import TagFilter, build_tag_filter_sql

router = APIRouter(tags=["memory"])


class CreateSessionRequest(BaseModel):
    metadata: dict[str, Any] | None = None


class CreateSessionResponse(BaseModel):
    request_id: str
    session_id: str
    org_id: str
    created_at: datetime
    metadata: dict[str, Any] | None = None


class LogMemoryRequest(BaseModel):
    role: str = Field(..., min_length=1, max_length=50)
    content: str = Field(..., min_length=1)
    session_id: UUID | None = None
    tags: list[str] | None = None
    metadata: dict[str, Any] | None = None


class LogMemoryResponse(BaseModel):
    request_id: str
    episode_id: str
    session_id: str | None
    created_at: datetime
    token_count: int
    embedding_status: str


class EpisodeEmbeddingStatusResponse(BaseModel):
    episode_id: str
    embedding_status: str
    embedding_generated_at: datetime | None
    embedding_error: str | None


class SessionEmbeddingStatusResponse(BaseModel):
    session_id: str
    pending: int
    ready: int
    failed: int
    total: int


class SessionCheckpointResponse(BaseModel):
    request_id: str
    checkpoint_id: str
    created_at: datetime
    message_count: int


class RestoreSessionRequest(BaseModel):
    checkpoint_id: UUID


class RestoreSessionResponse(BaseModel):
    request_id: str
    restored_message_count: int
    checkpoint_created_at: datetime


class MemoryQueryRequest(BaseModel):
    query: str | None = None
    session_id: UUID | None = None
    role: str | None = None
    tags: list[str] | None = None
    tag_filters: list[TagFilter] | None = None
    from_time: datetime | None = None
    to_time: datetime | None = None
    limit: int = Field(default=20, ge=1, le=100)
    offset: int = Field(default=0, ge=0)


class MemorySearchResult(BaseModel):
    episode_id: str
    content: str
    role: str
    score: float
    created_at: datetime
    tags: list[str] = Field(default_factory=list)


class MemorySearchResponse(BaseModel):
    request_id: str
    results: list[MemorySearchResult]
    total: int
    query_time_ms: int


class SessionListItem(BaseModel):
    session_id: str
    created_at: datetime
    metadata: dict[str, Any] | None = None
    message_count: int


class SessionListResponse(BaseModel):
    request_id: str
    sessions: list[SessionListItem]
    total: int
    limit: int
    offset: int


class SessionDetail(BaseModel):
    session_id: str
    org_id: str
    created_at: datetime
    metadata: dict[str, Any] | None = None


class SessionWindowMessage(BaseModel):
    role: str
    content: str
    tokens: int
    priority_score: float
    timestamp: datetime


class SessionDetailResponse(BaseModel):
    request_id: str
    session: SessionDetail
    messages: list[SessionWindowMessage]
    token_usage: dict[str, float | int]


class SessionHistoryItem(BaseModel):
    episode_id: str
    session_id: str | None
    role: str
    content: str
    tags: list[str] = Field(default_factory=list)
    metadata: dict[str, Any] | None = None
    created_at: datetime


class SessionHistoryResponse(BaseModel):
    request_id: str
    episodes: list[SessionHistoryItem]
    total: int
    limit: int
    offset: int


class CheckpointListItem(BaseModel):
    checkpoint_id: str
    created_at: datetime
    message_count: int


class CheckpointListResponse(BaseModel):
    request_id: str
    checkpoints: list[CheckpointListItem]


class DeleteEpisodeResponse(BaseModel):
    request_id: str
    deleted: bool
    episode_id: str
    soft: bool = True
    restorable_until: datetime | None = None


class DeleteSessionMemoriesResponse(BaseModel):
    request_id: str
    deleted_count: int
    session_id: str
    soft: bool = True
    restorable_until: datetime | None = None


class DeleteUserMemoriesResponse(BaseModel):
    request_id: str
    deleted_episodes: int
    deleted_sessions: int
    user_id: str
    soft: bool = True
    restorable_until: datetime | None = None


class HardDeleteEpisodeResponse(BaseModel):
    request_id: str
    deleted: bool
    episode_id: str
    soft: bool = False


class RestoreEpisodeResponse(BaseModel):
    request_id: str
    episode_id: str
    restored: bool


class MemoryDiffEpisode(BaseModel):
    episode_id: str
    session_id: str | None
    role: str
    content: str
    created_at: datetime
    tags: list[str] = Field(default_factory=list)


class MemoryDiffResponse(BaseModel):
    request_id: str
    added: list[MemoryDiffEpisode]
    period: dict[str, datetime]
    count: int


def _matches_tag_filters(tags: list[str], filters: list[TagFilter]) -> bool:
    """Python-side tag filter evaluation for the filter_only / time-based query path."""
    tag_set = set(tags)
    for tf in filters:
        prefix = f"{tf.key}:"
        matching = [t for t in tag_set if t.startswith(prefix)]

        if tf.op == "exists":
            if not matching:
                return False

        elif tf.op == "eq":
            target = f"{tf.key}:{tf.value}" if tf.value is not None else None
            if target is not None:
                if target not in tag_set:
                    return False
            else:
                if not matching:
                    return False

        elif tf.op == "ne":
            target = f"{tf.key}:{tf.value}" if tf.value is not None else None
            if target is not None:
                if target in tag_set:
                    return False
            else:
                if matching:
                    return False

        elif tf.op == "prefix":
            prefix_val = f"{tf.key}:{tf.value}"
            if not any(t.startswith(prefix_val) for t in tag_set):
                return False

        elif tf.op in ("gt", "gte", "lt", "lte"):
            threshold = float(tf.value)  # type: ignore[arg-type]
            found = False
            for t in matching:
                raw = t[len(prefix):]
                try:
                    num = float(raw)
                except ValueError:
                    continue
                ops = {"gt": num > threshold, "gte": num >= threshold,
                       "lt": num < threshold, "lte": num <= threshold}
                if ops[tf.op]:
                    found = True
                    break
            if not found:
                return False

    return True


def _apply_session_scope_filters(query, scope: MemoryScope):
    return (
        query.where(Session.org_id == UUID(scope.org_id))
        .where(Session.team_id == (UUID(scope.team_id) if scope.team_id else None))
        .where(Session.user_id == (UUID(scope.user_id) if scope.user_id else None))
        .where(Session.agent_id == (UUID(scope.agent_id) if scope.agent_id else None))
        .where(Session.not_deleted())
    )


def _apply_episode_scope_filters(query, scope: MemoryScope):
    return (
        query.where(Episode.org_id == UUID(scope.org_id))
        .where(Episode.team_id == (UUID(scope.team_id) if scope.team_id else None))
        .where(Episode.user_id == (UUID(scope.user_id) if scope.user_id else None))
        .where(Episode.agent_id == (UUID(scope.agent_id) if scope.agent_id else None))
        .where(Episode.not_deleted())
    )


async def _require_session_in_scope(
    db: AsyncSession, session_id: UUID, scope: MemoryScope
) -> Session:
    query = _apply_session_scope_filters(select(Session).where(Session.id == session_id), scope)
    result = await db.execute(query)
    session = result.scalar_one_or_none()
    if session is None:
        raise NotFoundError("Session not found", details={"code": SESSION_NOT_FOUND})
    return session


class MemoryQueryEngine:
    """Simple query engine facade for API retrieval endpoints."""

    def __init__(self, episodic: EpisodicMemory):
        self.episodic = episodic

    async def query(
        self, scope: MemoryScope, request: MemoryQueryRequest
    ) -> tuple[list[MemorySearchResult], int, int]:
        start = perf_counter()
        results: list[MemorySearchResult] = []

        if request.query:
            has_filters = any(
                [
                    request.tags,
                    request.tag_filters,
                    request.role,
                    request.from_time,
                    request.to_time,
                    request.session_id,
                ]
            )
            if has_filters:
                try:
                    semantic = await self.episodic.search_hybrid(
                        scope=scope,
                        query=request.query,
                        tags=request.tags,
                        tag_filters=request.tag_filters,
                        from_time=request.from_time,
                        to_time=request.to_time,
                        role=request.role,
                        session_id=request.session_id,
                        limit=request.limit,
                    )
                except Exception:
                    semantic = await self.episodic.search_semantic(
                        scope=scope,
                        query=request.query,
                        tag_filters=request.tag_filters,
                        limit=request.limit,
                    )
                    _filtered = []
                    for item in semantic:
                        episode = item.episode
                        if request.session_id and episode.session_id != request.session_id:
                            continue
                        if request.role and episode.role != request.role:
                            continue
                        if request.tags and not set(request.tags).intersection(
                            set(episode.tags or [])
                        ):
                            continue
                        if request.from_time and episode.created_at < request.from_time:
                            continue
                        if request.to_time and episode.created_at > request.to_time:
                            continue
                        _filtered.append(item)
                    semantic = _filtered
            else:
                semantic = await self.episodic.search_semantic(
                    scope=scope,
                    query=request.query,
                    limit=request.limit,
                )

            for item in semantic:
                episode = item.episode
                results.append(
                    MemorySearchResult(
                        episode_id=str(episode.id),
                        content=episode.content,
                        role=episode.role,
                        score=float(item.similarity_score),
                        created_at=episode.created_at,
                        tags=episode.tags or [],
                    )
                )
        else:
            episodes = await self.episodic.search_by_time(
                scope=scope,
                from_time=request.from_time,
                to_time=request.to_time,
                limit=request.limit + request.offset,
            )
            filtered = episodes
            if request.session_id:
                filtered = [ep for ep in filtered if ep.session_id == request.session_id]
            if request.role:
                filtered = [ep for ep in filtered if ep.role == request.role]
            if request.tags:
                filtered = [
                    ep for ep in filtered if set(request.tags).intersection(set(ep.tags or []))
                ]
            if request.tag_filters:
                filtered = [
                    ep for ep in filtered
                    if _matches_tag_filters(ep.tags or [], request.tag_filters)
                ]

            for ep in filtered[request.offset : request.offset + request.limit]:
                results.append(
                    MemorySearchResult(
                        episode_id=str(ep.id),
                        content=ep.content,
                        role=ep.role,
                        score=1.0,
                        created_at=ep.created_at,
                        tags=ep.tags or [],
                    )
                )

        elapsed_ms = int((perf_counter() - start) * 1000)
        return results, len(results), elapsed_ms


@router.post(
    "/sessions",
    response_model=StandardResponse[CreateSessionResponse],
    status_code=status.HTTP_201_CREATED,
)
async def create_session(
    payload: CreateSessionRequest,
    ctx: Annotated[RequestContext, Depends(require_auth)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> StandardResponse[CreateSessionResponse]:
    scope = ScopeResolver.resolve_writable_scope(ScopeResolver.from_request_context(ctx))

    session = Session(
        org_id=UUID(scope.org_id),
        team_id=UUID(scope.team_id) if scope.team_id else None,
        user_id=UUID(scope.user_id) if scope.user_id else None,
        agent_id=UUID(scope.agent_id) if scope.agent_id else None,
        metadata_=payload.metadata,
    )
    db.add(session)
    await db.flush()
    await db.refresh(session)
    await db.commit()

    return success(
        CreateSessionResponse(
            request_id=ctx.request_id,
            session_id=str(session.id),
            org_id=str(session.org_id),
            created_at=session.created_at,
            metadata=session.metadata_,
        ),
        request_id=ctx.request_id,
    )


@router.post(
    "/memory",
    response_model=StandardResponse[LogMemoryResponse],
    status_code=status.HTTP_201_CREATED,
)
async def log_memory(
    payload: LogMemoryRequest,
    ctx: Annotated[RequestContext, Depends(require_auth)],
    db: Annotated[AsyncSession, Depends(get_db)],
    redis: Annotated[Redis, Depends(get_redis)],
) -> StandardResponse[LogMemoryResponse]:
    scope = ScopeResolver.resolve_writable_scope(ScopeResolver.from_request_context(ctx))

    if payload.session_id is not None:
        await _require_session_in_scope(db, payload.session_id, scope)

    episodic = EpisodicMemory(db=db)
    short_term = ShortTermMemory(cache=CacheService(redis), db=db)

    episode = await episodic.log(
        scope=scope,
        role=payload.role,
        content=payload.content,
        tags=payload.tags,
        session_id=str(payload.session_id) if payload.session_id is not None else None,
        metadata=payload.metadata,
    )

    token_count = short_term.token_count(payload.content)

    if payload.session_id is not None:
        message = SessionMessage(
            role=payload.role,
            content=payload.content,
            tokens=token_count,
            priority_score=0.0,
            timestamp=datetime.now(UTC),
        )
        await short_term.add_message(str(payload.session_id), message)

    await db.commit()

    return success(
        LogMemoryResponse(
            request_id=ctx.request_id,
            episode_id=str(episode.id),
            session_id=str(episode.session_id) if episode.session_id is not None else None,
            created_at=episode.created_at,
            token_count=token_count,
            embedding_status=episode.embedding_status,
        ),
        request_id=ctx.request_id,
    )


@router.post(
    "/sessions/{session_id}/checkpoint",
    response_model=StandardResponse[SessionCheckpointResponse],
    status_code=status.HTTP_201_CREATED,
)
async def create_session_checkpoint(
    session_id: UUID,
    ctx: Annotated[RequestContext, Depends(require_auth)],
    db: Annotated[AsyncSession, Depends(get_db)],
    redis: Annotated[Redis, Depends(get_redis)],
) -> StandardResponse[SessionCheckpointResponse]:
    scope = ScopeResolver.resolve_writable_scope(ScopeResolver.from_request_context(ctx))
    await _require_session_in_scope(db, session_id, scope)

    short_term = ShortTermMemory(cache=CacheService(redis), db=db)
    checkpoint_id = await short_term.checkpoint(session_id=str(session_id), scope=scope)

    checkpoint = await db.execute(select(Episode).where(Episode.id == UUID(checkpoint_id)))
    checkpoint_episode = checkpoint.scalar_one_or_none()
    if checkpoint_episode is None:
        raise NotFoundError("Checkpoint not found", details={"code": CHECKPOINT_NOT_FOUND})

    await db.commit()

    return success(
        SessionCheckpointResponse(
            request_id=ctx.request_id,
            checkpoint_id=str(checkpoint_id),
            created_at=checkpoint_episode.created_at,
            message_count=int((checkpoint_episode.metadata_ or {}).get("message_count", 0)),
        ),
        request_id=ctx.request_id,
    )


@router.post(
    "/sessions/{session_id}/restore",
    response_model=StandardResponse[RestoreSessionResponse],
)
async def restore_session_checkpoint(
    session_id: UUID,
    payload: RestoreSessionRequest,
    ctx: Annotated[RequestContext, Depends(require_auth)],
    db: Annotated[AsyncSession, Depends(get_db)],
    redis: Annotated[Redis, Depends(get_redis)],
) -> StandardResponse[RestoreSessionResponse]:
    scope = ScopeResolver.resolve_writable_scope(ScopeResolver.from_request_context(ctx))
    await _require_session_in_scope(db, session_id, scope)

    query = _apply_episode_scope_filters(
        select(Episode)
        .where(Episode.id == payload.checkpoint_id)
        .where(Episode.session_id == session_id)
        .where(Episode.role == "checkpoint"),
        scope,
    )
    result = await db.execute(query)
    checkpoint_episode = result.scalar_one_or_none()
    if checkpoint_episode is None:
        raise NotFoundError("Checkpoint not found", details={"code": CHECKPOINT_NOT_FOUND})

    short_term = ShortTermMemory(cache=CacheService(redis), db=db)

    try:
        restored_message_count = await short_term.restore_from_checkpoint(
            session_id=str(session_id),
            checkpoint_id=str(payload.checkpoint_id),
            scope=scope,
        )
    except ValueError as exc:
        raise NotFoundError(str(exc), details={"code": CHECKPOINT_NOT_FOUND}) from exc

    await db.commit()

    return success(
        RestoreSessionResponse(
            request_id=ctx.request_id,
            restored_message_count=restored_message_count,
            checkpoint_created_at=checkpoint_episode.created_at,
        ),
        request_id=ctx.request_id,
    )


@router.post("/memory/search", response_model=StandardResponse[MemorySearchResponse])
@limiter.limit(get_search_limit)
async def search_memory(
    request: Request,
    response: Response,
    payload: MemoryQueryRequest,
    ctx: Annotated[RequestContext, Depends(require_auth)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> StandardResponse[MemorySearchResponse]:
    scope = ScopeResolver.resolve_writable_scope(ScopeResolver.from_request_context(ctx))
    engine = MemoryQueryEngine(EpisodicMemory(db=db))

    if payload.session_id is not None:
        await _require_session_in_scope(db, payload.session_id, scope)

    results, total, query_time_ms = await engine.query(scope, payload)
    return success(
        MemorySearchResponse(
            request_id=ctx.request_id,
            results=results,
            total=total,
            query_time_ms=query_time_ms,
        ),
        request_id=ctx.request_id,
    )


@router.get("/sessions", response_model=StandardResponse[SessionListResponse])
async def list_sessions(
    ctx: Annotated[RequestContext, Depends(require_auth)],
    db: Annotated[AsyncSession, Depends(get_db)],
    limit: int = Query(20, ge=1),
    offset: int = Query(0, ge=0),
) -> StandardResponse[SessionListResponse]:
    scope = ScopeResolver.resolve_writable_scope(ScopeResolver.from_request_context(ctx))

    total_query = _apply_session_scope_filters(select(func.count(Session.id)), scope)
    total_result = await db.execute(total_query)
    total = int(total_result.scalar_one())

    sessions_query = _apply_session_scope_filters(
        select(Session).order_by(Session.updated_at.desc()).limit(limit).offset(offset),
        scope,
    )
    sessions_result = await db.execute(sessions_query)
    sessions = list(sessions_result.scalars().all())

    counts_query = (
        _apply_episode_scope_filters(
            select(Episode.session_id, func.count(Episode.id))
            .where(Episode.session_id.in_([session.id for session in sessions]))
            .group_by(Episode.session_id),
            scope,
        )
        if sessions
        else None
    )

    counts: dict[UUID, int] = {}
    if counts_query is not None:
        count_result = await db.execute(counts_query)
        counts = {row[0]: int(row[1]) for row in count_result.all()}

    payload = [
        SessionListItem(
            session_id=str(session.id),
            created_at=session.created_at,
            metadata=session.metadata_,
            message_count=counts.get(session.id, 0),
        )
        for session in sessions
    ]

    return success(
        SessionListResponse(
            request_id=ctx.request_id,
            sessions=payload,
            total=total,
            limit=limit,
            offset=offset,
        ),
        request_id=ctx.request_id,
    )


@router.get("/sessions/{session_id}", response_model=StandardResponse[SessionDetailResponse])
async def get_session(
    session_id: UUID,
    ctx: Annotated[RequestContext, Depends(require_auth)],
    db: Annotated[AsyncSession, Depends(get_db)],
    redis: Annotated[Redis, Depends(get_redis)],
) -> StandardResponse[SessionDetailResponse]:
    scope = ScopeResolver.resolve_writable_scope(ScopeResolver.from_request_context(ctx))
    session = await _require_session_in_scope(db, session_id, scope)

    short_term = ShortTermMemory(cache=CacheService(redis), db=db)
    messages = await short_term.get_context(str(session_id))

    used_tokens = sum(message.tokens for message in messages)
    max_tokens = short_term.MAX_TOKENS
    percentage = round((used_tokens / max_tokens) * 100, 2) if max_tokens > 0 else 0.0

    return success(
        SessionDetailResponse(
            request_id=ctx.request_id,
            session=SessionDetail(
                session_id=str(session.id),
                org_id=str(session.org_id),
                created_at=session.created_at,
                metadata=session.metadata_,
            ),
            messages=[SessionWindowMessage(**message.__dict__) for message in messages],
            token_usage={"used": used_tokens, "max": max_tokens, "percentage": percentage},
        ),
        request_id=ctx.request_id,
    )


@router.get(
    "/sessions/{session_id}/history",
    response_model=StandardResponse[SessionHistoryResponse],
)
async def get_session_history(
    session_id: UUID,
    ctx: Annotated[RequestContext, Depends(require_auth)],
    db: Annotated[AsyncSession, Depends(get_db)],
    limit: int = Query(20, ge=1),
    offset: int = Query(0, ge=0),
    from_time: datetime | None = None,
    to_time: datetime | None = None,
) -> StandardResponse[SessionHistoryResponse]:
    scope = ScopeResolver.resolve_writable_scope(ScopeResolver.from_request_context(ctx))
    await _require_session_in_scope(db, session_id, scope)

    total_query = _apply_episode_scope_filters(
        select(func.count(Episode.id)).where(Episode.session_id == session_id),
        scope,
    )
    if from_time is not None:
        total_query = total_query.where(Episode.created_at >= from_time)
    if to_time is not None:
        total_query = total_query.where(Episode.created_at <= to_time)

    total_result = await db.execute(total_query)
    total = int(total_result.scalar_one())

    episodes_query = _apply_episode_scope_filters(
        select(Episode)
        .where(Episode.session_id == session_id)
        .order_by(Episode.created_at.desc())
        .limit(limit)
        .offset(offset),
        scope,
    )
    if from_time is not None:
        episodes_query = episodes_query.where(Episode.created_at >= from_time)
    if to_time is not None:
        episodes_query = episodes_query.where(Episode.created_at <= to_time)

    episodes_result = await db.execute(episodes_query)
    episodes = list(episodes_result.scalars().all())

    return success(
        SessionHistoryResponse(
            request_id=ctx.request_id,
            episodes=[
                SessionHistoryItem(
                    episode_id=str(ep.id),
                    session_id=str(ep.session_id) if ep.session_id else None,
                    role=ep.role,
                    content=ep.content,
                    tags=ep.tags or [],
                    metadata=ep.metadata_,
                    created_at=ep.created_at,
                )
                for ep in episodes
            ],
            total=total,
            limit=limit,
            offset=offset,
        ),
        request_id=ctx.request_id,
    )


@router.get(
    "/sessions/{session_id}/checkpoints",
    response_model=StandardResponse[CheckpointListResponse],
)
async def list_session_checkpoints(
    session_id: UUID,
    ctx: Annotated[RequestContext, Depends(require_auth)],
    db: Annotated[AsyncSession, Depends(get_db)],
    redis: Annotated[Redis, Depends(get_redis)],
) -> StandardResponse[CheckpointListResponse]:
    scope = ScopeResolver.resolve_writable_scope(ScopeResolver.from_request_context(ctx))
    await _require_session_in_scope(db, session_id, scope)

    short_term = ShortTermMemory(cache=CacheService(redis), db=db)
    checkpoints = await short_term.list_checkpoints(session_id=str(session_id), scope=scope)

    return success(
        CheckpointListResponse(
            request_id=ctx.request_id,
            checkpoints=[CheckpointListItem(**item) for item in checkpoints],
        ),
        request_id=ctx.request_id,
    )


@router.delete("/memory/{episode_id}", response_model=StandardResponse[DeleteEpisodeResponse])
async def delete_memory_episode(
    episode_id: UUID,
    ctx: Annotated[RequestContext, Depends(require_auth)],
    db: Annotated[AsyncSession, Depends(get_db)],
    redis: Annotated[Redis, Depends(get_redis)],
) -> StandardResponse[DeleteEpisodeResponse]:
    scope = ScopeResolver.resolve_writable_scope(ScopeResolver.from_request_context(ctx))
    service = ForgettingService(db=db, redis=redis)
    result = await service.delete_episode(
        episode_id=episode_id,
        scope=scope,
        request_id=ctx.request_id,
        actor_user_id=ctx.user_id,
    )
    if not result.deleted:
        raise NotFoundError("Episode not found", details={"code": EPISODE_NOT_FOUND})

    return success(
        DeleteEpisodeResponse(
            request_id=ctx.request_id,
            deleted=True,
            episode_id=str(episode_id),
            soft=True,
            restorable_until=result.restorable_until,
        ),
        request_id=ctx.request_id,
    )


@router.delete(
    "/memory/session/{session_id}",
    response_model=StandardResponse[DeleteSessionMemoriesResponse],
)
async def delete_session_memories(
    session_id: UUID,
    ctx: Annotated[RequestContext, Depends(require_auth)],
    db: Annotated[AsyncSession, Depends(get_db)],
    redis: Annotated[Redis, Depends(get_redis)],
) -> StandardResponse[DeleteSessionMemoriesResponse]:
    scope = ScopeResolver.resolve_writable_scope(ScopeResolver.from_request_context(ctx))
    await _require_session_in_scope(db, session_id, scope)

    service = ForgettingService(db=db, redis=redis)
    deleted_count, restorable_until = await service.delete_session_memories(
        session_id=session_id,
        scope=scope,
        request_id=ctx.request_id,
        actor_user_id=ctx.user_id,
    )

    return success(
        DeleteSessionMemoriesResponse(
            request_id=ctx.request_id,
            deleted_count=deleted_count,
            session_id=str(session_id),
            soft=True,
            restorable_until=restorable_until,
        ),
        request_id=ctx.request_id,
    )


@router.delete(
    "/memory/user/{user_id}",
    response_model=StandardResponse[DeleteUserMemoriesResponse],
)
async def delete_user_memories(
    user_id: UUID,
    ctx: Annotated[RequestContext, Depends(require_auth)],
    db: Annotated[AsyncSession, Depends(get_db)],
    redis: Annotated[Redis, Depends(get_redis)],
) -> StandardResponse[DeleteUserMemoriesResponse]:
    if ctx.user_id is not None or ctx.agent_id is not None:
        raise AuthorizationError(
            "Org-level authority required",
            details={"code": ORG_LEVEL_REQUIRED},
        )

    from datetime import timedelta

    service = ForgettingService(db=db, redis=redis)
    result = await service.delete_user_memories(
        user_id=user_id,
        org_id=ctx.org_id,
        request_id=ctx.request_id,
        actor_user_id=ctx.user_id,
    )
    restorable_until = datetime.now(UTC) + timedelta(days=30)

    return success(
        DeleteUserMemoriesResponse(
            request_id=ctx.request_id,
            deleted_episodes=result.deleted_episodes,
            deleted_sessions=result.deleted_sessions,
            user_id=str(user_id),
            soft=True,
            restorable_until=restorable_until,
        ),
        request_id=ctx.request_id,
    )


@router.delete(
    "/memory/{episode_id}/hard",
    response_model=StandardResponse[HardDeleteEpisodeResponse],
)
async def hard_delete_memory_episode(
    episode_id: UUID,
    ctx: Annotated[RequestContext, Depends(require_auth)],
    db: Annotated[AsyncSession, Depends(get_db)],
    redis: Annotated[Redis, Depends(get_redis)],
) -> StandardResponse[HardDeleteEpisodeResponse]:
    """Immediately and permanently delete an episode, bypassing the 30-day grace period.

    Enterprise-gated: in production this endpoint should require an org-admin scope.
    For now any authenticated caller within org scope may call it. All hard-deletes
    are audit-logged with the full actor identity.
    """
    scope = ScopeResolver.resolve_writable_scope(ScopeResolver.from_request_context(ctx))
    service = ForgettingService(db=db, redis=redis)
    deleted = await service.hard_delete_episode(
        episode_id=episode_id,
        scope=scope,
        request_id=ctx.request_id,
        actor_user_id=ctx.user_id,
    )
    if not deleted:
        raise NotFoundError("Episode not found", details={"code": EPISODE_NOT_FOUND})

    return success(
        HardDeleteEpisodeResponse(
            request_id=ctx.request_id,
            deleted=True,
            episode_id=str(episode_id),
            soft=False,
        ),
        request_id=ctx.request_id,
    )


@router.post(
    "/memory/{episode_id}/restore",
    response_model=StandardResponse[RestoreEpisodeResponse],
)
async def restore_memory_episode(
    episode_id: UUID,
    ctx: Annotated[RequestContext, Depends(require_auth)],
    db: Annotated[AsyncSession, Depends(get_db)],
    redis: Annotated[Redis, Depends(get_redis)],
) -> StandardResponse[RestoreEpisodeResponse]:
    """Restore a soft-deleted episode within the 30-day grace window.

    Returns 404 if the episode was never found or already hard-deleted by the purge job.
    Returns 410 Gone if the episode exists but the 30-day window has expired
    (this state is transient — the purge job will hard-delete it shortly after).
    """
    from fastapi import Response as FastAPIResponse

    scope = ScopeResolver.resolve_writable_scope(ScopeResolver.from_request_context(ctx))
    service = ForgettingService(db=db, redis=redis)

    try:
        episode = await service.restore_episode(
            episode_id=episode_id,
            scope=scope,
            request_id=ctx.request_id,
            actor_user_id=ctx.user_id,
        )
    except ValueError as exc:
        from fastapi import HTTPException
        raise HTTPException(
            status_code=status.HTTP_410_GONE,
            detail=f"Grace period expired: {exc}",
        )

    if episode is None:
        raise NotFoundError("Episode not found", details={"code": EPISODE_NOT_FOUND})

    return success(
        RestoreEpisodeResponse(
            request_id=ctx.request_id,
            episode_id=str(episode_id),
            restored=True,
        ),
        request_id=ctx.request_id,
    )


@router.get(
    "/memory/{episode_id}/status",
    response_model=StandardResponse[EpisodeEmbeddingStatusResponse],
)
async def get_episode_embedding_status(
    episode_id: UUID,
    ctx: Annotated[RequestContext, Depends(require_auth)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> StandardResponse[EpisodeEmbeddingStatusResponse]:
    """Return the embedding generation status for a single episode."""
    from app.error_codes import EPISODE_NOT_FOUND

    scope = ScopeResolver.resolve_writable_scope(ScopeResolver.from_request_context(ctx))
    query = _apply_episode_scope_filters(
        select(Episode).where(Episode.id == episode_id), scope
    )
    result = await db.execute(query)
    episode = result.scalar_one_or_none()
    if episode is None:
        raise NotFoundError("Episode not found", details={"code": EPISODE_NOT_FOUND})

    return success(
        EpisodeEmbeddingStatusResponse(
            episode_id=str(episode.id),
            embedding_status=episode.embedding_status,
            embedding_generated_at=episode.embedding_generated_at,
            embedding_error=episode.embedding_error,
        ),
        request_id=ctx.request_id,
    )


@router.get(
    "/sessions/{session_id}/embedding-status",
    response_model=StandardResponse[SessionEmbeddingStatusResponse],
)
async def get_session_embedding_status(
    session_id: UUID,
    ctx: Annotated[RequestContext, Depends(require_auth)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> StandardResponse[SessionEmbeddingStatusResponse]:
    """Return aggregate embedding status counts for all episodes in a session."""
    scope = ScopeResolver.resolve_writable_scope(ScopeResolver.from_request_context(ctx))
    await _require_session_in_scope(db, session_id, scope)

    count_query = _apply_episode_scope_filters(
        select(Episode.embedding_status, func.count(Episode.id))
        .where(Episode.session_id == session_id)
        .group_by(Episode.embedding_status),
        scope,
    )
    rows = (await db.execute(count_query)).all()
    counts = {status: int(cnt) for status, cnt in rows}

    return success(
        SessionEmbeddingStatusResponse(
            session_id=str(session_id),
            pending=counts.get("pending", 0),
            ready=counts.get("ready", 0),
            failed=counts.get("failed", 0),
            total=sum(counts.values()),
        ),
        request_id=ctx.request_id,
    )


@router.get("/memory/diff", response_model=StandardResponse[MemoryDiffResponse])
async def memory_diff(
    from_time: datetime = Query(...),
    to_time: datetime = Query(...),
    session_id: UUID | None = Query(None),
    user_id: UUID | None = Query(None),
    role: str | None = Query(None),
    tags: list[str] | None = Query(None),
    ctx: Annotated[RequestContext, Depends(require_auth)] = None,
    db: Annotated[AsyncSession, Depends(get_db)] = None,
) -> StandardResponse[MemoryDiffResponse]:
    if to_time < from_time:
        raise ValidationError("to_time must be >= from_time", details={"code": INVALID_TIME_RANGE})

    scope = ScopeResolver.resolve_writable_scope(ScopeResolver.from_request_context(ctx))

    query = _apply_episode_scope_filters(
        select(Episode)
        .where(Episode.created_at >= from_time)
        .where(Episode.created_at <= to_time)
        .order_by(Episode.created_at.asc()),
        scope,
    )

    if session_id is not None:
        await _require_session_in_scope(db, session_id, scope)
        query = query.where(Episode.session_id == session_id)
    if user_id is not None:
        query = query.where(Episode.user_id == user_id)
    if role is not None:
        query = query.where(Episode.role == role)
    if tags:
        query = query.where(Episode.tags.op("&&")(tags))

    result = await db.execute(query)
    episodes = list(result.scalars().all())

    added = [
        MemoryDiffEpisode(
            episode_id=str(ep.id),
            session_id=str(ep.session_id) if ep.session_id else None,
            role=ep.role,
            content=ep.content,
            created_at=ep.created_at,
            tags=ep.tags or [],
        )
        for ep in episodes
    ]

    return success(
        MemoryDiffResponse(
            request_id=ctx.request_id,
            added=added,
            period={"from": from_time, "to": to_time},
            count=len(added),
        ),
        request_id=ctx.request_id,
    )
