export class IcoCache {
    baseUrl;
    apiKey;
    constructor(options) {
        this.baseUrl = options.baseUrl;
        this.apiKey = options.apiKey;
    }
    async request(endpoint, body) {
        const headers = { 'Content-Type': 'application/json' };
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
    async resolve(query, context, callback) {
        const data = await this.request('/v1/query', { query, context });
        if (data.source !== 'MISS') {
            return data.response;
        }
        const generated = await callback();
        await this.request('/v1/ingest', { query, context, response: generated });
        return generated;
    }
    async query(query, context = null) {
        return this.request('/v1/query', { query, context });
    }
    async ingest(query, context, response) {
        await this.request('/v1/ingest', { query, context, response });
    }
    async health() {
        const res = await fetch(`${this.baseUrl}/v1/health`);
        return res.json();
    }
}
export function icoCache(options) {
    return new IcoCache(options);
}
