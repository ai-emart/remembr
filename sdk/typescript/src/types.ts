export interface Session {
  request_id: string;
  session_id: string;
  org_id: string;
  created_at: string;
  metadata?: Record<string, unknown> | null;
}

export interface Episode {
  episode_id: string;
  session_id?: string | null;
  role: string;
  content: string;
  created_at: string;
  tags: string[];
  metadata?: Record<string, unknown> | null;
}

export interface SearchResult {
  episode_id: string;
  content: string;
  role: string;
  score: number;
  created_at: string;
  tags: string[];
}

export interface MemoryQueryResult {
  request_id: string;
  results: SearchResult[];
  total: number;
  query_time_ms: number;
}

export interface SearchWeights {
  semantic?: number;
  keyword?: number;
  recency?: number;
}

export interface CheckpointInfo {
  checkpoint_id: string;
  created_at: string;
  message_count: number;
}

export interface RemembrConfig {
  apiKey?: string;
  baseUrl?: string;
  timeout?: number;
}

/** Parameters for creating a session. */
export interface CreateSessionParams {
  /** Optional custom metadata attached to the created session. */
  metadata?: Record<string, unknown>;
}

/** Parameters for getting a single session by id. */
export interface GetSessionParams {
  /** The target session identifier. */
  sessionId: string;
}

/** Parameters for listing sessions with pagination. */
export interface ListSessionsParams {
  /** Maximum number of sessions to return. Must be greater than 0. */
  limit?: number;
  /** Number of sessions to skip. Must be greater than or equal to 0. */
  offset?: number;
}

/** Parameters for storing a new memory episode. */
export interface StoreMemoryParams {
  /** Episode content to persist. */
  content: string;
  /** Role label associated with the memory (for example: user, assistant). */
  role?: string;
  /** Optional session id to associate with the episode. */
  sessionId?: string;
  /** Optional tags for filtering and organization. */
  tags?: string[];
  /** Optional metadata attached to the stored episode. */
  metadata?: Record<string, unknown>;
}

/** Parameters for searching stored memory episodes. */
export interface SearchMemoryParams {
  /** Search query text. */
  query: string;
  /** Optional session scope for the search query. */
  sessionId?: string;
  /** Optional flat tag strings for backward-compatible exact-match filtering. */
  tags?: string[];
  /** Optional structured tag filters with key, value, and comparison operator. */
  tagFilters?: TagFilter[];
  /** Optional lower timestamp bound. Serialized as ISO8601 when sent. */
  fromTime?: Date;
  /** Optional upper timestamp bound. Serialized as ISO8601 when sent. */
  toTime?: Date;
  /** Maximum number of results to return. Must be greater than 0. */
  limit?: number;
  /** Search strategy. Must be one of: semantic, keyword, hybrid. */
  searchMode?: 'semantic' | 'keyword' | 'hybrid';
  /** Optional hybrid ranking weights. Only used when searchMode is `hybrid`. */
  weights?: SearchWeights;
  /** Deprecated alias for `searchMode`. */
  mode?: 'semantic' | 'keyword' | 'hybrid';
}

/** Parameters for loading session history. */
export interface SessionHistoryParams {
  /** Session identifier to read history from. */
  sessionId: string;
  /** Maximum number of episodes to return. Must be greater than 0. */
  limit?: number;
}

/** Parameters for creating a checkpoint. */
export interface CheckpointParams {
  /** Session identifier for checkpoint creation. */
  sessionId: string;
}

/** Parameters for restoring a checkpoint. */
export interface RestoreCheckpointParams {
  /** Session identifier to restore into. */
  sessionId: string;
  /** Checkpoint identifier to restore from. */
  checkpointId: string;
}

/** Parameters for listing checkpoints for a session. */
export interface ListCheckpointsParams {
  /** Session identifier whose checkpoints should be listed. */
  sessionId: string;
}

/** Parameters for forgetting a single episode. */
export interface ForgetEpisodeParams {
  /** Episode identifier to delete. */
  episodeId: string;
}

/** Parameters for forgetting all memory in a session. */
export interface ForgetSessionParams {
  /** Session identifier to purge. */
  sessionId: string;
}

/** Parameters for forgetting all data tied to a user. */
export interface ForgetUserParams {
  /** User identifier to purge. */
  userId: string;
}

/** Parameters for exporting memory data. */
export interface ExportParams {
  /** Output format. `json` returns an AsyncIterable of episode objects; `csv` returns a Blob. */
  format?: 'json' | 'csv';
  /** Optional lower bound for created_at (ISO 8601). */
  fromDate?: Date;
  /** Optional upper bound for created_at (ISO 8601). */
  toDate?: Date;
  /** Limit export to a single session. */
  sessionId?: string;
  /** Include soft-deleted episodes (default: false). */
  includeDeleted?: boolean;
}

/** JSON export result — an async iterable of episode objects. */
export type JsonExportResult = AsyncIterable<Record<string, unknown>>;

/** Structured tag filter for ``key:value`` tag matching. */
export interface TagFilter {
  /** Tag key (the part before the colon in ``key:value`` tags). */
  key: string;
  /** Tag value (the part after the colon). Required for ``gt``, ``gte``, ``lt``, ``lte``, and ``prefix`` ops. */
  value?: string;
  /** Comparison operator. Defaults to ``'eq'``. */
  op?: 'eq' | 'ne' | 'gt' | 'gte' | 'lt' | 'lte' | 'exists' | 'prefix';
}

/** Idempotency options for mutating write methods. */
export interface IdempotencyOptions {
  /** Optional idempotency key (≤ 255 chars). Same key → same response for 24 h. */
  idempotencyKey?: string;
}
