export interface IcoCacheOptions {
  baseUrl: string;
  apiKey?: string;
  semanticThreshold?: number;
}

export class IcoCache {
  private baseUrl: string;
  private apiKey?: string;

  constructor(options: IcoCacheOptions) {
    this.baseUrl = options.baseUrl;
    this.apiKey = options.apiKey;
  }

  private async request(endpoint: string, body: unknown): Promise<unknown> {
    const headers: Record<string, string> = { 'Content-Type': 'application/json' };
    if (this.apiKey) {
      headers['X-API-Key'] = this.apiKey;
    }

    const res = await fetch(`${this.baseUrl}${endpoint}`, {
      method: 'POST',
      headers,
      body: JSON.stringify(body),
    });

    if (!res.ok) {
      throw new Error(`ICO-Cache request failed: ${res.status} ${res.statusText}`);
    }

    return res.json();
  }

  async resolve<T>(query: string, context: string | null, callback: () => Promise<T>): Promise<T> {
    const data = await this.request('/v1/query', { query, context }) as {
      source: string;
      response: T;
    };

    if (data.source !== 'MISS') {
      return data.response;
    }

    const generated = await callback();

    await this.request('/v1/ingest', { query, context, response: generated });

    return generated;
  }

  async query(query: string, context: string | null = null): Promise<{ source: string; response: unknown }> {
    return this.request('/v1/query', { query, context }) as Promise<{ source: string; response: unknown }>;
  }

  async ingest(query: string, context: string | null, response: unknown): Promise<void> {
    await this.request('/v1/ingest', { query, context, response });
  }

  async health(): Promise<{ status: string; backends: Record<string, string> }> {
    const res = await fetch(`${this.baseUrl}/v1/health`);
    return res.json() as Promise<{ status: string; backends: Record<string, string> }>;
  }
}

export function icoCache(options: IcoCacheOptions) {
  return new IcoCache(options);
}