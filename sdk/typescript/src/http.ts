import {
  AuthenticationError,
  NotFoundError,
  RateLimitError,
  RemembrError,
  ServerError,
} from './errors';
import { RemembrConfig } from './types';

const DEFAULT_BASE_URL = 'http://localhost:8000/api/v1';
const DEFAULT_TIMEOUT_MS = 30_000;
const MAX_ATTEMPTS = 4;

export class RemembrHttp {
  private readonly apiKey?: string;
  private readonly baseUrl: string;
  private readonly timeout: number;

  constructor(config: RemembrConfig = {}) {
    this.apiKey = config.apiKey;
    this.baseUrl = (config.baseUrl ?? DEFAULT_BASE_URL).replace(/\/+$/, '');
    this.timeout = config.timeout ?? DEFAULT_TIMEOUT_MS;
  }

  async request<T = Record<string, unknown>>(
    method: string,
    path: string,
    options: {
      params?: Record<string, string | number | boolean | undefined | null>;
      body?: Record<string, unknown>;
      headers?: Record<string, string>;
    } = {}
  ): Promise<T> {
    let lastError: unknown;

    for (let attempt = 1; attempt <= MAX_ATTEMPTS; attempt += 1) {
      try {
        const response = await this.fetchWithTimeout(method, path, options);

        if (response.status === 429 || (response.status >= 500 && response.status <= 599)) {
          const retryError = await this.toError(response);
          if (attempt < MAX_ATTEMPTS) {
            await this.sleep(this.backoffMs(attempt));
            continue;
          }
          throw retryError;
        }

        if (response.status >= 400) {
          throw await this.toError(response);
        }

        const payload = (await this.parseJson(response)) as Record<string, unknown>;
        if (payload && typeof payload === 'object' && 'data' in payload) {
          return payload.data as T;
        }
        return payload as T;
      } catch (error) {
        lastError = error;

        if (this.isAbortError(error) || error instanceof TypeError) {
          if (attempt < MAX_ATTEMPTS) {
            await this.sleep(this.backoffMs(attempt));
            continue;
          }

          if (this.isAbortError(error)) {
            throw new ServerError('Request to Remembr API timed out.', { code: 'TIMEOUT' });
          }
          throw new ServerError('HTTP communication error with Remembr API.');
        }

        if (error instanceof RemembrError) {
          throw error;
        }

        if (attempt >= MAX_ATTEMPTS) {
          throw new ServerError('HTTP communication error with Remembr API.');
        }
      }
    }

    if (lastError instanceof RemembrError) {
      throw lastError;
    }
    throw new ServerError('HTTP communication error with Remembr API.');
  }

  private async fetchWithTimeout(
    method: string,
    path: string,
    options: {
      params?: Record<string, string | number | boolean | undefined | null>;
      body?: Record<string, unknown>;
      headers?: Record<string, string>;
    }
  ): Promise<Response> {
    const controller = new AbortController();
    const timeoutId = setTimeout(() => controller.abort(), this.timeout);

    try {
      const headers: Record<string, string> = {
        Accept: 'application/json',
        'Content-Type': 'application/json',
        ...options.headers,
      };
      if (this.apiKey) {
        headers['X-API-Key'] = this.apiKey;
      }

      return await fetch(this.buildUrl(path, options.params), {
        method,
        headers,
        body: options.body ? JSON.stringify(options.body) : undefined,
        signal: controller.signal,
      });
    } finally {
      clearTimeout(timeoutId);
    }
  }

  private buildUrl(path: string, params?: Record<string, string | number | boolean | undefined | null>): string {
    const url = new URL(`${this.baseUrl}${path.startsWith('/') ? path : `/${path}`}`);
    if (params) {
      Object.entries(params).forEach(([key, value]) => {
        if (value !== undefined && value !== null) {
          url.searchParams.set(key, String(value));
        }
      });
    }
    return url.toString();
  }

  private async parseJson(response: Response): Promise<unknown> {
    try {
      return await response.json();
    } catch {
      throw new ServerError('Failed to parse JSON response from Remembr API.', {
        statusCode: response.status,
      });
    }
  }

  private async toError(response: Response): Promise<RemembrError> {
    let message = `Remembr API request failed with status code ${response.status}.`;
    let code: string | undefined;
    let details: Record<string, unknown> | undefined;
    let requestId: string | undefined;

    try {
      const payload = (await response.json()) as Record<string, unknown>;
      const error = payload?.error as Record<string, unknown> | undefined;
      if (error && typeof error === 'object') {
        if (typeof error.message === 'string') {
          message = error.message;
        }
        if (typeof error.code === 'string') {
          code = error.code;
        }
        if (error.details && typeof error.details === 'object') {
          details = error.details as Record<string, unknown>;
        }
        if (typeof error.request_id === 'string') {
          requestId = error.request_id;
        }
      }
    } catch {
      // noop: fallback to generic error message
    }

    const options = { statusCode: response.status, code, details, requestId };

    if (response.status === 401 || response.status === 403) {
      return new AuthenticationError(message, options);
    }
    if (response.status === 404) {
      return new NotFoundError(message, options);
    }
    if (response.status === 429) {
      return new RateLimitError(message, options);
    }
    if (response.status >= 500 && response.status <= 599) {
      return new ServerError(message, options);
    }
    return new RemembrError(message, options);
  }

  private backoffMs(attempt: number): number {
    return Math.min(2 ** (attempt - 1), 4) * 1000;
  }

  private sleep(ms: number): Promise<void> {
    return new Promise((resolve) => setTimeout(resolve, ms));
  }

  private isAbortError(error: unknown): boolean {
    return error instanceof DOMException && error.name === 'AbortError';
  }
}
