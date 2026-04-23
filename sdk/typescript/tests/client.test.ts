import {
  AuthenticationError,
  NotFoundError,
  RateLimitError,
  RemembrClient,
  ServerError,
  Session,
} from '../src';
import { installMockFetch, installSequentialMockFetch, jsonResponse } from './helpers/mock-fetch';

const ORIGINAL_FETCH = global.fetch;

describe('RemembrClient', () => {
  afterEach(() => {
    jest.useRealTimers();
    jest.restoreAllMocks();
    global.fetch = ORIGINAL_FETCH;
  });

  test('constructor throws without api key', () => {
    const originalProcess = (globalThis as any).process;
    (globalThis as any).process = { env: {} };
    expect(() => new RemembrClient()).toThrow(AuthenticationError);
    (globalThis as any).process = originalProcess;
  });

  test('createSession returns a Session-like payload', async () => {
    const mock = installMockFetch(() =>
      jsonResponse({
        data: {
          request_id: 'req_1',
          session_id: 'sess_1',
          org_id: 'org_1',
          created_at: '2025-01-01T00:00:00.000Z',
          metadata: { team: 'sdk' },
        },
      })
    );

    const client = new RemembrClient({ apiKey: 'test-key' });
    const session: Session = await client.createSession({ team: 'sdk' });

    expect(session.session_id).toBe('sess_1');
    expect(session.request_id).toBe('req_1');
    expect(mock.calls[0].init?.method).toBe('POST');
  });

  test('getSession maps nested response and throws on invalid payload', async () => {
    const okMock = installMockFetch(() =>
      jsonResponse({
        data: {
          request_id: 'req_1',
          session: {
            session_id: 'sess_1',
            org_id: 'org_1',
            created_at: '2025-01-01T00:00:00.000Z',
            metadata: { foo: 'bar' },
          },
        },
      })
    );

    const client = new RemembrClient({ apiKey: 'test-key' });
    const session = await client.getSession('sess_1');
    expect(session.org_id).toBe('org_1');
    expect(session.metadata).toEqual({ foo: 'bar' });

    okMock.restore();

    installMockFetch(() => jsonResponse({ data: { request_id: 'x', session: null } }));
    await expect(client.getSession('sess_1')).rejects.toBeInstanceOf(ServerError);
  });

  test('listSessions handles defaults, pagination and validates params', async () => {
    const mock = installMockFetch(() =>
      jsonResponse({
        data: {
          request_id: 'r1',
          org_id: 'o1',
          sessions: [{ session_id: 's1', created_at: '2025-01-01T00:00:00.000Z', metadata: null }],
        },
      })
    );

    const client = new RemembrClient({ apiKey: 'test-key' });
    const rows = await client.listSessions();
    expect(rows).toHaveLength(1);
    expect(String(mock.calls[0].input)).toContain('limit=20');
    expect(String(mock.calls[0].input)).toContain('offset=0');

    await expect(client.listSessions({ limit: 0 })).rejects.toThrow('limit must be greater than 0');
    await expect(client.listSessions({ offset: -1 })).rejects.toThrow(
      'offset must be greater than or equal to 0'
    );
  });

  test('store sends correct request body and default role/tags', async () => {
    const mock = installSequentialMockFetch([
      jsonResponse({ data: { episode_id: 'ep_1', session_id: 'sess_1', created_at: '2025-01-01T00:00:00.000Z' } }),
      jsonResponse({ data: { episode_id: 'ep_2', session_id: null, created_at: '2025-01-01T00:00:00.000Z' } }),
    ]);

    const client = new RemembrClient({ apiKey: 'test-key' });
    await client.store({
      content: 'hello',
      role: 'assistant',
      sessionId: 'sess_1',
      tags: ['a', 'b'],
      metadata: { source: 'test' },
    });

    const rawBody = mock.calls[0].init?.body as string;
    const body = JSON.parse(rawBody);
    expect(body).toEqual({
      content: 'hello',
      role: 'assistant',
      session_id: 'sess_1',
      tags: ['a', 'b'],
      metadata: { source: 'test' },
    });

    const result2 = await client.store({ content: 'hello2' });
    expect(result2.role).toBe('user');
    expect(result2.tags).toEqual([]);
  });

  test('search handles minimal/full combinations and validation branches', async () => {
    const fromTime = new Date('2025-01-01T00:00:00.000Z');
    const toTime = new Date('2025-01-02T00:00:00.000Z');

    const mock = installSequentialMockFetch([
      jsonResponse({ data: { request_id: 'r1', total: 0, query_time_ms: 5, results: [] } }),
      jsonResponse({ data: { request_id: 'r2', total: 1, query_time_ms: 8, results: [] } }),
    ]);

    const client = new RemembrClient({ apiKey: 'test-key' });

    await client.search({ query: 'minimal' });
    await client.search({
      query: 'full',
      sessionId: 'sess_2',
      tags: ['x'],
      fromTime,
      toTime,
      limit: 10,
      searchMode: 'semantic',
      weights: { semantic: 0.6, keyword: 0.3, recency: 0.1 },
    });

    const body1 = JSON.parse((mock.calls[0].init?.body as string) ?? '{}');
    expect(body1).toMatchObject({ query: 'minimal', limit: 20, search_mode: 'hybrid' });

    const body2 = JSON.parse((mock.calls[1].init?.body as string) ?? '{}');
    expect(body2).toEqual({
      query: 'full',
      session_id: 'sess_2',
      tags: ['x'],
      from_time: fromTime.toISOString(),
      to_time: toTime.toISOString(),
      limit: 10,
      search_mode: 'semantic',
      weights: { semantic: 0.6, keyword: 0.3, recency: 0.1 },
    });

    await expect(client.search({ query: 'x', searchMode: 'bad' as any })).rejects.toThrow(
      'searchMode must be one of: semantic, keyword, hybrid'
    );
    await expect(client.search({ query: 'x', limit: 0 })).rejects.toThrow('limit must be greater than 0');
    await expect(client.search({ query: 'x', fromTime: toTime, toTime: fromTime })).rejects.toThrow(
      'fromTime must be less than or equal to toTime'
    );
  });

  test('session history/checkpoint/restore/checkpoint listing + forget methods', async () => {
    installSequentialMockFetch([
      jsonResponse({ data: { episodes: [{ episode_id: 'e1', role: 'user', content: 'c', created_at: 't', tags: [] }] } }),
      jsonResponse({ data: { checkpoint_id: 'cp_1', created_at: 't', message_count: 4 } }),
      jsonResponse({ data: { restoredMessageCount: 4 } }),
      jsonResponse({ data: { checkpoints: [{ checkpoint_id: 'cp_1', created_at: 't', message_count: 4 }] } }),
      jsonResponse({ data: { deleted: true } }),
      jsonResponse({ data: { deletedCount: 2 } }),
      jsonResponse({ data: { deletedEpisodes: 2, deletedSessions: 1 } }),
    ]);

    const client = new RemembrClient({ apiKey: 'test-key' });

    const history = await client.getSessionHistory('sess_1');
    expect(history).toHaveLength(1);
    await expect(client.getSessionHistory('sess_1', { limit: 0 })).rejects.toThrow(
      'limit must be greater than 0'
    );

    const checkpoint = await client.checkpoint('sess_1');
    const restored = await client.restore('sess_1', checkpoint.checkpoint_id);
    const checkpoints = await client.listCheckpoints('sess_1');
    const deletedEpisode = await client.forgetEpisode('ep_1');
    const deletedSession = await client.forgetSession('sess_1');
    const deletedUser = await client.forgetUser('user_1');

    expect(restored.restoredMessageCount).toBe(4);
    expect(checkpoints).toHaveLength(1);
    expect(deletedEpisode.deleted).toBe(true);
    expect(deletedSession.deletedCount).toBe(2);
    expect(deletedUser.deletedSessions).toBe(1);
  });

  test('throws AuthenticationError on 401', async () => {
    installMockFetch(() => jsonResponse({ error: { message: 'invalid key', code: 'AUTH' } }, 401));

    const client = new RemembrClient({ apiKey: 'test-key' });
    await expect(client.createSession()).rejects.toBeInstanceOf(AuthenticationError);
  });

  test('throws RateLimitError on 429 with retry behavior', async () => {
    jest.useFakeTimers();

    const mock = installMockFetch(() => jsonResponse({ error: { message: 'rate limited' } }, 429));

    const client = new RemembrClient({ apiKey: 'test-key' });
    const promise = client.createSession();
    const assertion = expect(promise).rejects.toBeInstanceOf(RateLimitError);

    await jest.advanceTimersByTimeAsync(7100);
    await assertion;
    expect(mock.fetchMock).toHaveBeenCalledTimes(4);
  });

  test('throws NotFoundError on 404', async () => {
    installMockFetch(() => jsonResponse({ error: { message: 'not found' } }, 404));

    const client = new RemembrClient({ apiKey: 'test-key' });
    await expect(client.getSession('missing')).rejects.toBeInstanceOf(NotFoundError);
  });

  test('webhook lifecycle methods map responses correctly', async () => {
    installSequentialMockFetch([
      jsonResponse({
        data: {
          id: 'wh_1',
          org_id: 'org_1',
          url: 'https://example.com/hooks',
          events: ['memory.stored'],
          active: true,
          created_at: '2026-01-01T00:00:00.000Z',
          updated_at: '2026-01-01T00:00:00.000Z',
          last_delivery_at: null,
          last_delivery_status: null,
          failure_count: 0,
          secret: 'secret_once',
        },
      }),
      jsonResponse({
        data: [
          {
            id: 'wh_1',
            org_id: 'org_1',
            url: 'https://example.com/hooks',
            events: ['memory.stored'],
            active: true,
            created_at: '2026-01-01T00:00:00.000Z',
            updated_at: '2026-01-01T00:00:00.000Z',
            last_delivery_at: null,
            last_delivery_status: null,
            failure_count: 0,
          },
        ],
      }),
      jsonResponse({
        data: {
          id: 'wh_1',
          org_id: 'org_1',
          url: 'https://example.com/hooks-updated',
          events: ['checkpoint.created'],
          active: false,
          created_at: '2026-01-01T00:00:00.000Z',
          updated_at: '2026-01-02T00:00:00.000Z',
          last_delivery_at: null,
          last_delivery_status: null,
          failure_count: 0,
        },
      }),
      jsonResponse({
        data: {
          id: 'wh_1',
          org_id: 'org_1',
          url: 'https://example.com/hooks-updated',
          events: ['checkpoint.created'],
          active: false,
          created_at: '2026-01-01T00:00:00.000Z',
          updated_at: '2026-01-02T00:00:00.000Z',
          last_delivery_at: null,
          last_delivery_status: null,
          failure_count: 0,
        },
      }),
      jsonResponse({
        data: {
          id: 'wh_1',
          org_id: 'org_1',
          url: 'https://example.com/hooks-updated',
          events: ['checkpoint.created'],
          active: false,
          created_at: '2026-01-01T00:00:00.000Z',
          updated_at: '2026-01-02T00:00:00.000Z',
          last_delivery_at: null,
          last_delivery_status: null,
          failure_count: 0,
          secret: 'secret_rotated',
        },
      }),
      jsonResponse({
        data: [
          {
            id: 'del_1',
            webhook_id: 'wh_1',
            event: 'memory.stored',
            payload: { episode_id: 'ep_1' },
            status: 'delivered',
            attempts: 1,
            last_attempt_at: '2026-01-02T00:00:00.000Z',
            response_status_code: 204,
            response_body_snippet: 'ok',
            created_at: '2026-01-02T00:00:00.000Z',
          },
        ],
      }),
      jsonResponse({ data: { delivery_id: 'del_test', event: 'webhook.test' } }),
      jsonResponse({ data: { deleted: true, webhook_id: 'wh_1' } }),
    ]);

    const client = new RemembrClient({ apiKey: 'test-key' });

    const created = await client.webhooks.create({
      url: 'https://example.com/hooks',
      events: ['memory.stored'],
    });
    const listed = await client.webhooks.list();
    const updated = await client.webhooks.update('wh_1', {
      url: 'https://example.com/hooks-updated',
      events: ['checkpoint.created'],
      active: false,
    });
    const fetched = await client.webhooks.get('wh_1');
    const rotated = await client.webhooks.rotateSecret('wh_1');
    const deliveries = await client.webhooks.deliveries('wh_1');
    const tested = await client.webhooks.test('wh_1');
    const deleted = await client.webhooks.delete('wh_1');

    expect(created.secret).toBe('secret_once');
    expect(listed).toHaveLength(1);
    expect(updated.active).toBe(false);
    expect(fetched.id).toBe('wh_1');
    expect(rotated.secret).toBe('secret_rotated');
    expect(deliveries[0].event).toBe('memory.stored');
    expect(tested.delivery_id).toBe('del_test');
    expect(deleted.deleted).toBe(true);
  });

  test('webhook validation errors are raised for empty inputs', async () => {
    const client = new RemembrClient({ apiKey: 'test-key' });

    await expect(
      client.webhooks.create({
        url: 'https://example.com/hooks',
        events: [],
      })
    ).rejects.toThrow('events must not be empty');

    await expect(client.webhooks.get('')).rejects.toThrow(
      'webhookId is required and must be a non-empty string'
    );
    await expect(client.webhooks.update('wh_1', { events: [] })).rejects.toThrow(
      'events must not be empty'
    );
    await expect(client.webhooks.deliveries('wh_1', 0)).rejects.toThrow(
      'limit must be greater than 0'
    );
  });

  test('search serializes tagFilters payload', async () => {
    const mock = installMockFetch(() =>
      jsonResponse({ data: { request_id: 'r1', total: 0, query_time_ms: 1, results: [] } })
    );

    const client = new RemembrClient({ apiKey: 'test-key' });
    await client.search({
      query: 'tagged',
      tagFilters: [{ key: 'topic', value: 'ai', op: 'prefix' }, { key: 'priority' }],
    });

    const body = JSON.parse((mock.calls[0].init?.body as string) ?? '{}');
    expect(body.tag_filters).toEqual([
      { key: 'topic', value: 'ai', op: 'prefix' },
      { key: 'priority', op: 'eq' },
    ]);
  });

  test('export handles csv success/failure and json streaming parser', async () => {
    const encoder = new TextEncoder();
    const stream = new ReadableStream<Uint8Array>({
      start(controller) {
        controller.enqueue(encoder.encode('{"id":1},{"id":2,"text":"a\\\\\\"b"}'));
        controller.close();
      },
    });

    installSequentialMockFetch([
      new Response('a,b\\n1,2\\n', { status: 200, headers: { 'Content-Type': 'text/csv' } }),
      new Response('nope', { status: 500 }),
      new Response(stream, { status: 200, headers: { 'Content-Type': 'application/json' } }),
      new Response('error', { status: 500 }),
      new Response('[]', { status: 200 }),
    ]);

    const client = new RemembrClient({ apiKey: 'test-key', baseUrl: 'http://localhost:8000' });

    const csvBlob = await client.export({ format: 'csv' });
    expect(csvBlob).toBeInstanceOf(Blob);

    await expect(client.export({ format: 'csv' })).rejects.toBeInstanceOf(ServerError);

    const jsonStream = await client.export({
      format: 'json',
      fromDate: new Date('2026-01-01T00:00:00.000Z'),
      toDate: new Date('2026-01-02T00:00:00.000Z'),
      sessionId: 'sess_1',
      includeDeleted: true,
    });
    const rows: Array<Record<string, unknown>> = [];
    for await (const row of jsonStream as AsyncIterable<Record<string, unknown>>) {
      rows.push(row);
    }
    expect(rows).toEqual([{ id: 1 }]);

    const failingStream = await client.export({ format: 'json' });
    await expect(
      (async () => {
        for await (const _ of failingStream as AsyncIterable<Record<string, unknown>>) {
          // no-op
        }
      })()
    ).rejects.toBeInstanceOf(ServerError);

  });

  test('requireNonEmpty guards blank identifiers', async () => {
    const client = new RemembrClient({ apiKey: 'test-key' });
    await expect(client.getSession('   ')).rejects.toThrow(
      'sessionId is required and must be a non-empty string'
    );
  });
});
