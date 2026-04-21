import { AuthenticationError, ServerError } from './errors';
import { RemembrHttp } from './http';
import {
  CheckpointInfo,
  Episode,
  ExportParams,
  IdempotencyOptions,
  JsonExportResult,
  ListSessionsParams,
  MemoryQueryResult,
  RemembrConfig,
  SearchMemoryParams,
  Session,
  StoreMemoryParams,
  TagFilter,
} from './types';

const VALID_SEARCH_MODES = new Set(['semantic', 'keyword', 'hybrid']);

interface RestoreResponse {
  restoredMessageCount: number;
}

interface ForgetEpisodeResponse {
  deleted: boolean;
}

interface ForgetSessionResponse {
  deletedCount: number;
}

interface ForgetUserResponse {
  deletedEpisodes: number;
  deletedSessions: number;
}

/** Remembr API client exposing session, memory, checkpoint, and forget operations. */
export class RemembrClient {
  private readonly http: RemembrHttp;

  constructor(config: RemembrConfig = {}) {
    const apiKey = config.apiKey ?? this.getApiKeyFromEnv();
    if (!apiKey) {
      throw new AuthenticationError(
        'Missing API key. Pass `apiKey` or set REMEMBR_API_KEY environment variable.'
      );
    }

    this.http = new RemembrHttp({ ...config, apiKey });
  }

  /**
   * Create a new memory session.
   * @param metadata Optional metadata dictionary stored alongside the created session.
   * @param options Optional idempotency options.
   */
  async createSession(
    metadata?: Record<string, unknown>,
    options?: IdempotencyOptions
  ): Promise<Session> {
    const data = await this.http.request<Session>('POST', '/sessions', {
      body: { metadata: metadata ?? {} },
      headers: options?.idempotencyKey ? { 'Idempotency-Key': options.idempotencyKey } : undefined,
    });
    return data;
  }

  /**
   * Fetch metadata for a single session.
   * @param sessionId The session identifier.
   */
  async getSession(sessionId: string): Promise<Session> {
    this.requireNonEmpty(sessionId, 'sessionId');

    const data = await this.http.request<Record<string, unknown>>('GET', `/sessions/${sessionId}`);
    const session = data.session as Record<string, unknown> | undefined;

    if (!session || typeof session !== 'object') {
      throw new ServerError('Invalid session payload returned by Remembr API.');
    }

    return {
      request_id: String(data.request_id ?? ''),
      session_id: String(session.session_id ?? ''),
      org_id: String(session.org_id ?? ''),
      created_at: String(session.created_at ?? ''),
      metadata: (session.metadata as Record<string, unknown> | null | undefined) ?? null,
    };
  }

  /**
   * List sessions for the authenticated scope.
   * @param params Pagination options.
   */
  async listSessions(): Promise<Session[]>;
  async listSessions(params: ListSessionsParams): Promise<Session[]>;
  async listSessions(params: ListSessionsParams = {}): Promise<Session[]> {
    const limit = params.limit ?? 20;
    const offset = params.offset ?? 0;
    this.validatePagination(limit, offset);

    const data = await this.http.request<Record<string, unknown>>('GET', '/sessions', {
      params: { limit, offset },
    });

    const sessions = Array.isArray(data.sessions) ? data.sessions : [];
    const requestId = String(data.request_id ?? '');
    const orgId = String(data.org_id ?? '');

    return sessions
      .filter((session) => typeof session === 'object' && session !== null)
      .map((session) => {
        const s = session as Record<string, unknown>;
        return {
          request_id: requestId,
          session_id: String(s.session_id ?? ''),
          org_id: orgId,
          created_at: String(s.created_at ?? ''),
          metadata: (s.metadata as Record<string, unknown> | null | undefined) ?? null,
        };
      });
  }

  /**
   * Store a memory episode.
   * @param params Memory payload to persist.
   * @param options Optional idempotency options.
   */
  async store(params: StoreMemoryParams, options?: IdempotencyOptions): Promise<Episode> {
    this.requireNonEmpty(params.content, 'content');
    const role = params.role ?? 'user';
    this.requireNonEmpty(role, 'role');

    if (params.sessionId) {
      this.requireNonEmpty(params.sessionId, 'sessionId');
    }

    const data = await this.http.request<Record<string, unknown>>('POST', '/memory', {
      body: {
        content: params.content,
        role,
        session_id: params.sessionId,
        tags: params.tags ?? [],
        metadata: params.metadata ?? {},
      },
      headers: options?.idempotencyKey ? { 'Idempotency-Key': options.idempotencyKey } : undefined,
    });

    return {
      episode_id: String(data.episode_id ?? ''),
      session_id: (data.session_id as string | null | undefined) ?? null,
      role,
      content: params.content,
      created_at: String(data.created_at ?? ''),
      tags: params.tags ?? [],
      metadata: params.metadata ?? null,
    };
  }

  /**
   * Search memory episodes.
   * @param params Search filters and query options.
   */
  async search(params: SearchMemoryParams): Promise<MemoryQueryResult> {
    this.requireNonEmpty(params.query, 'query');

    const searchMode = params.mode ?? params.searchMode ?? 'hybrid';
    if (!VALID_SEARCH_MODES.has(searchMode)) {
      throw new Error('searchMode must be one of: semantic, keyword, hybrid');
    }

    const limit = params.limit ?? 20;
    if (limit < 1) {
      throw new Error('limit must be greater than 0');
    }

    if (params.sessionId) {
      this.requireNonEmpty(params.sessionId, 'sessionId');
    }

    if (params.fromTime && params.toTime && params.fromTime > params.toTime) {
      throw new Error('fromTime must be less than or equal to toTime');
    }

    const tagFilters = params.tagFilters?.map((tf: TagFilter) => {
      const out: Record<string, string> = { key: tf.key, op: tf.op ?? 'eq' };
      if (tf.value !== undefined) out.value = tf.value;
      return out;
    });

    const data = await this.http.request<MemoryQueryResult>('POST', '/memory/search', {
      body: {
        query: params.query,
        session_id: params.sessionId,
        tags: params.tags,
        tag_filters: tagFilters,
        from_time: params.fromTime?.toISOString(),
        to_time: params.toTime?.toISOString(),
        limit,
        search_mode: searchMode,
        weights: params.weights,
      },
    });

    return data;
  }

  /**
   * Get a session's memory history.
   * @param sessionId Session identifier.
   * @param params Optional history retrieval options.
   */
  async getSessionHistory(sessionId: string): Promise<Episode[]>;
  async getSessionHistory(sessionId: string, params: { limit?: number }): Promise<Episode[]>;
  async getSessionHistory(sessionId: string, params: { limit?: number } = {}): Promise<Episode[]> {
    this.requireNonEmpty(sessionId, 'sessionId');

    const limit = params.limit ?? 50;
    if (limit < 1) {
      throw new Error('limit must be greater than 0');
    }

    const data = await this.http.request<Record<string, unknown>>('GET', `/sessions/${sessionId}/history`, {
      params: { limit },
    });

    return Array.isArray(data.episodes) ? (data.episodes as Episode[]) : [];
  }

  /**
   * Create a session checkpoint.
   * @param sessionId Session identifier to checkpoint.
   */
  async checkpoint(sessionId: string): Promise<CheckpointInfo> {
    this.requireNonEmpty(sessionId, 'sessionId');
    return this.http.request<CheckpointInfo>('POST', `/sessions/${sessionId}/checkpoint`);
  }

  /**
   * Restore a session to a checkpoint.
   * @param sessionId Session identifier to restore.
   * @param checkpointId Checkpoint identifier to restore from.
   */
  async restore(sessionId: string, checkpointId: string): Promise<RestoreResponse> {
    this.requireNonEmpty(sessionId, 'sessionId');
    this.requireNonEmpty(checkpointId, 'checkpointId');

    return this.http.request<RestoreResponse>('POST', `/sessions/${sessionId}/restore`, {
      body: { checkpoint_id: checkpointId },
    });
  }

  /**
   * List checkpoints for a session.
   * @param sessionId Session identifier to inspect.
   */
  async listCheckpoints(sessionId: string): Promise<CheckpointInfo[]> {
    this.requireNonEmpty(sessionId, 'sessionId');

    const data = await this.http.request<Record<string, unknown>>('GET', `/sessions/${sessionId}/checkpoints`);
    return Array.isArray(data.checkpoints) ? (data.checkpoints as CheckpointInfo[]) : [];
  }

  /**
   * Delete a single memory episode.
   * @param episodeId Episode identifier to delete.
   */
  async forgetEpisode(episodeId: string): Promise<ForgetEpisodeResponse> {
    this.requireNonEmpty(episodeId, 'episodeId');
    return this.http.request<ForgetEpisodeResponse>('DELETE', `/memory/${episodeId}`);
  }

  /**
   * Delete all memory episodes for a session.
   * @param sessionId Session identifier to purge.
   */
  async forgetSession(sessionId: string): Promise<ForgetSessionResponse> {
    this.requireNonEmpty(sessionId, 'sessionId');
    return this.http.request<ForgetSessionResponse>('DELETE', `/memory/session/${sessionId}`);
  }

  /**
   * Delete all memories and sessions for a user.
   * @param userId User identifier to purge.
   */
  async forgetUser(userId: string): Promise<ForgetUserResponse> {
    this.requireNonEmpty(userId, 'userId');
    return this.http.request<ForgetUserResponse>('DELETE', `/memory/user/${userId}`);
  }

  /**
   * Export all episodes for the authenticated scope.
   *
   * @param params Export options (format, date range, session, include_deleted).
   * @returns An `AsyncIterable<Record<string, unknown>>` for JSON, or a `Blob` for CSV.
   *
   * @example JSON streaming
   * ```ts
   * for await (const episode of await client.export({ format: 'json' })) {
   *   console.log(episode.content);
   * }
   * ```
   *
   * @example CSV download
   * ```ts
   * const blob = await client.export({ format: 'csv' }) as Blob;
   * ```
   */
  async export(params: ExportParams = {}): Promise<JsonExportResult | Blob> {
    const format = params.format ?? 'json';
    const url = this.buildExportUrl(params);

    const headers: Record<string, string> = {
      Accept: format === 'csv' ? 'text/csv' : 'application/json',
      'Content-Type': 'application/json',
    };
    if (this.http['apiKey']) {
      headers.Authorization = `Bearer ${this.http['apiKey']}`;
    }

    const baseUrl = this.http['baseUrl'];
    const fullUrl = `${baseUrl}${url.startsWith('/') ? url : `/${url}`}`;

    if (format === 'csv') {
      const response = await fetch(fullUrl, { method: 'GET', headers });
      if (!response.ok) {
        throw new ServerError(`Export failed with status ${response.status}`);
      }
      return response.blob();
    }

    // JSON: return an AsyncIterable that streams and parses objects
    return this.streamJsonExport(fullUrl, headers);
  }

  private buildExportUrl(params: ExportParams): string {
    const qs = new URLSearchParams();
    qs.set('format', params.format ?? 'json');
    if (params.fromDate) qs.set('from_date', params.fromDate.toISOString());
    if (params.toDate) qs.set('to_date', params.toDate.toISOString());
    if (params.sessionId) qs.set('session_id', params.sessionId);
    if (params.includeDeleted) qs.set('include_deleted', 'true');
    return `/export?${qs.toString()}`;
  }

  private async *streamJsonExport(
    url: string,
    headers: Record<string, string>
  ): AsyncIterable<Record<string, unknown>> {
    const response = await fetch(url, { method: 'GET', headers });
    if (!response.ok || !response.body) {
      throw new ServerError(`Export failed with status ${response.status}`);
    }

    const reader = response.body.getReader();
    const decoder = new TextDecoder();
    let buf = '';
    let depth = 0;
    let inStr = false;
    let escapeNext = false;

    try {
      while (true) {
        const { done, value } = await reader.read();
        if (done) break;

        const chunk = decoder.decode(value, { stream: true });
        for (const ch of chunk) {
          if (escapeNext) { buf += ch; escapeNext = false; continue; }
          if (ch === '\\' && inStr) { buf += ch; escapeNext = true; continue; }
          if (ch === '"') inStr = !inStr;
          if (!inStr) {
            if (ch === '{') depth += 1;
            else if (ch === '}') depth -= 1;
          }
          buf += ch;

          if (depth === 0 && buf.trim().startsWith('{')) {
            const objStr = buf.trim().replace(/,$/, '').trim();
            if (objStr) {
              try { yield JSON.parse(objStr) as Record<string, unknown>; } catch { /* skip */ }
            }
            buf = '';
          }
        }
      }
    } finally {
      reader.releaseLock();
    }
  }

  private getApiKeyFromEnv(): string | undefined {
    const processValue = (globalThis as { process?: { env?: Record<string, string | undefined> } }).process;
    return processValue?.env?.REMEMBR_API_KEY;
  }

  private requireNonEmpty(value: string, paramName: string): void {
    if (!value || !value.trim()) {
      throw new Error(`${paramName} is required and must be a non-empty string`);
    }
  }

  private validatePagination(limit: number, offset: number): void {
    if (limit < 1) {
      throw new Error('limit must be greater than 0');
    }
    if (offset < 0) {
      throw new Error('offset must be greater than or equal to 0');
    }
  }
}
