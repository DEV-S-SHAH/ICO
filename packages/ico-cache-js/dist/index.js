"use strict";
Object.defineProperty(exports, "__esModule", { value: true });
exports.IcoCache = void 0;
exports.icoCache = icoCache;
class IcoCache {
    constructor(options) {
        this.baseUrl = options.baseUrl;
    }
    async resolve(query, context, callback) {
        const res = await fetch(`${this.baseUrl}/resolve`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ query, context })
        });
        const data = await res.json();
        if (data.source !== 'MISS') {
            return data.response;
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
exports.IcoCache = IcoCache;
function icoCache(options) {
    return new IcoCache(options);
}
