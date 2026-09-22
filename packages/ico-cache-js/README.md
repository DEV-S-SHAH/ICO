# ico-cache-js

JavaScript & TypeScript SDK for the **ICO-Cache** semantic caching middleware.

Reduce LLM API token costs and response latencies in Node.js and browser applications by resolving cached LLM completions across exact (L1), semantic (L2), and context-aware (L3) cache tiers before calling expensive model APIs.

## Installation

```bash
npm install ico-cache-js
```

## Quickstart

```typescript
import { IcoCache } from 'ico-cache-js';

const cache = new IcoCache({
  baseUrl: 'http://localhost:8000/v1'
});

async function askLLM(prompt: string): Promise<string> {
  return await cache.resolve(prompt, null, async () => {
    // This callback only executes on a cache MISS
    const response = await callYourLLMProvider(prompt);
    return response;
  });
}
```

## Features

- **TypeScript Native**: Full typing support for query responses and configurations.
- **Single-Flight Integration**: Transparently queries the ICO-Cache gateway and writes back generated completions only on cache misses.
- **Cross-Platform**: Compatible with Node.js 20+, Deno, Bun, and modern browsers.

## License

MIT
