export interface IcoCacheOptions {
  baseUrl: string;
  semanticThreshold?: number;
}

export class IcoCache {
  private baseUrl: string;

  constructor(options: IcoCacheOptions) {
    this.baseUrl = options.baseUrl;
  }

  async resolve<T>(query: string, context: string | null, callback: () => Promise<T>): Promise<T> {
    const res = await fetch(`${this.baseUrl}/resolve`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ query, context })
    });
    
    const data = await res.json();
    
    if (data.source !== 'MISS') {
      return data.response as T;
    }
    
    const generated = await callback();
    
    await fetch(`${this.baseUrl}/ingest`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ query, context, response: generated })
    });
    
    return generated;
  }
}

export function icoCache(options: IcoCacheOptions) {
  return new IcoCache(options);
}
