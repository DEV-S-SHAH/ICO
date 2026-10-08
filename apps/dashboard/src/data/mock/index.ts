// Realistic mock data for the Synapse dashboard

import type {
  Request,
  ModelMetrics,
  ProviderMetrics,
  CacheMetrics,
  CacheEntry,
  OverviewMetrics,
  TimeSeriesPoint,
  DashboardEvent,
  HealthCheck,
} from '@/types'

const MODELS = [
  'claude-sonnet-4.6',
  'claude-opus-4.5',
  'gpt-5',
  'gpt-5-mini',
  'gemini-2.5-pro',
  'gemini-2.5-flash',
  'qwen-2.5-72b',
  'llama-3.1-405b',
  'llama-3.1-70b',
  'mistral-large-2',
] as const

type ModelName = typeof MODELS[number]

const PROVIDERS: Array<{ name: string; models: ModelName[] }> = [
  { name: 'Anthropic', models: ['claude-sonnet-4.6', 'claude-opus-4.5'] },
  { name: 'OpenAI', models: ['gpt-5', 'gpt-5-mini'] },
  { name: 'Google', models: ['gemini-2.5-pro', 'gemini-2.5-flash'] },
  { name: 'Alibaba', models: ['qwen-2.5-72b'] },
  { name: 'Meta', models: ['llama-3.1-405b', 'llama-3.1-70b'] },
  { name: 'Mistral', models: ['mistral-large-2'] },
]

const ENDPOINTS = [
  '/v1/messages',
  '/v1/chat/completions',
  '/v1/completions',
  '/v1/embeddings',
] as const

const CACHE_LAYERS = ['L1', 'L2', 'L3'] as const
const REQUEST_STATUSES = ['OK', 'OK', 'OK', 'OK', 'ERROR', 'TIMEOUT'] as const

function randomItem<T>(arr: readonly T[]): T {
  return arr[Math.floor(Math.random() * arr.length)]
}

function randomInt(min: number, max: number): number {
  return Math.floor(Math.random() * (max - min + 1)) + min
}

function randomFloat(min: number, max: number, decimals = 2): number {
  return parseFloat((Math.random() * (max - min) + min).toFixed(decimals))
}

function generateRequestId(): string {
  return `req_${Math.random().toString(36).substring(2, 10)}`
}

function generateCacheKey(): string {
  return `cache_${Math.random().toString(36).substring(2, 16)}`
}

function generateTimestamp(hoursAgo: number): string {
  const date = new Date()
  date.setHours(date.getHours() - hoursAgo)
  date.setMinutes(randomInt(0, 59))
  date.setSeconds(randomInt(0, 59))
  return date.toISOString()
}

export function generateMockRequests(count: number): Request[] {
  const requests: Request[] = []

  for (let i = 0; i < count; i++) {
    const hoursAgo = randomFloat(0, 72, 1)
    const model = randomItem(MODELS)
    const provider = PROVIDERS.find(p => p.models.includes(model))?.name || 'Unknown'
    const endpoint = randomItem(ENDPOINTS)
    const isCacheHit = Math.random() < 0.73
    const cacheLayer = isCacheHit ? randomItem(CACHE_LAYERS) : null
    const cacheStatus = isCacheHit ? 'HIT' : 'MISS'
    const inputTokens = randomInt(500, 8000)
    const outputTokens = randomInt(50, 500)
    const cachedInputTokens = isCacheHit ? randomInt(200, inputTokens) : 0
    const latency = isCacheHit ? randomInt(80, 300) : randomInt(300, 1500)
    const latencySaved = isCacheHit ? randomInt(100, 800) : 0
    const inputCost = (inputTokens / 1000) * randomFloat(0.001, 0.015)
    const outputCost = (outputTokens / 1000) * randomFloat(0.002, 0.03)
    const totalCost = inputCost + outputCost
    const savedCost = (cachedInputTokens / 1000) * randomFloat(0.001, 0.015)

    const trace: Request['trace'] = {
      id: 'trace-root',
      name: 'Request',
      duration: latency,
      status: 'success',
      children: [
        { id: 'auth', name: 'Authentication', duration: randomInt(2, 8), status: 'success' },
        { id: 'l1', name: 'L1 Exact Cache', duration: randomInt(1, 5), status: cacheLayer === 'L1' ? 'success' : 'success', result: cacheLayer === 'L1' ? 'HIT' : 'MISS' },
        { id: 'l2', name: 'L2 Semantic Cache', duration: randomInt(10, 50), status: cacheLayer === 'L2' ? 'success' : 'success', result: cacheLayer === 'L2' ? `HIT (${randomFloat(0.85, 0.99)})` : 'MISS' },
        { id: 'l3', name: 'L3 Context Cache', duration: randomInt(15, 80), status: cacheLayer === 'L3' ? 'success' : 'success', result: cacheLayer === 'L3' ? `HIT (${randomFloat(0.75, 0.92)})` : 'SKIPPED' },
        { id: 'provider', name: provider, duration: latency - (isCacheHit ? latencySaved : 0), status: 'success', result: `Latency: ${latency}ms` },
        { id: 'response', name: 'Response Processing', duration: randomInt(2, 10), status: 'success' },
        { id: 'write', name: 'Cache Write', duration: randomInt(5, 20), status: 'success', result: 'Written to L1, L2' },
      ],
    }

    const cacheDecision = CACHE_LAYERS.map(layer => ({
      layer,
      status: (layer === cacheLayer ? 'HIT' : (layer === 'L3' && cacheLayer !== 'L3' ? 'SKIPPED' : 'MISS')) as 'HIT' | 'MISS' | 'SKIPPED' | 'WRITE',
      similarity: layer === cacheLayer ? randomFloat(0.85, 0.99) : layer === 'L2' ? randomFloat(0.7, 0.84) : undefined,
      tokensSaved: layer === cacheLayer ? cachedInputTokens : 0,
      latencySaved: layer === cacheLayer ? latencySaved : 0,
      duration: layer === 'L1' ? randomInt(1, 5) : layer === 'L2' ? randomInt(10, 50) : randomInt(15, 80),
    }))

    requests.push({
      id: generateRequestId(),
      timestamp: generateTimestamp(hoursAgo),
      model,
      provider,
      endpoint,
      tokens: {
        input: inputTokens,
        output: outputTokens,
        total: inputTokens + outputTokens,
        cachedInput: cachedInputTokens,
      },
      cache: {
        layer: cacheLayer,
        status: cacheStatus,
        similarity: cacheLayer ? randomFloat(0.85, 0.99) : undefined,
        tokensSaved: cachedInputTokens,
        latencySaved,
      },
      latency,
      cost: {
        input: inputCost,
        output: outputCost,
        total: totalCost,
        saved: savedCost,
      },
      status: randomItem(REQUEST_STATUSES),
      trace,
      cacheDecision,
      requestBody: {
        model,
        messages: [{ role: 'user', content: 'Sample request content...' }],
        temperature: 0.7,
        max_tokens: 1000,
      },
      responseBody: {
        id: generateRequestId(),
        model,
        choices: [{ message: { role: 'assistant', content: 'Sample response content...' } }],
        usage: { prompt_tokens: inputTokens, completion_tokens: outputTokens, total_tokens: inputTokens + outputTokens },
      },
    })
  }

  return requests.sort((a, b) => new Date(b.timestamp).getTime() - new Date(a.timestamp).getTime())
}

export function generateMockModels(): ModelMetrics[] {
  return MODELS.map(model => {
    const provider = PROVIDERS.find(p => p.models.includes(model))?.name || 'Unknown'
    const requests = randomInt(1000, 50000)
    const cacheHitRate = randomFloat(0.45, 0.85)
    const inputTokens = randomInt(100000, 5000000)
    const outputTokens = randomInt(50000, 2000000)
    const cachedTokens = Math.floor(inputTokens * cacheHitRate * randomFloat(0.3, 0.7))
    const avgLatency = randomInt(150, 800)
    const cost = (inputTokens / 1000) * randomFloat(0.001, 0.015) + (outputTokens / 1000) * randomFloat(0.002, 0.03)

    return {
      id: model.toLowerCase().replace(/[^a-z0-9]/g, '-'),
      name: model,
      provider,
      requests,
      inputTokens,
      outputTokens,
      cachedTokens,
      cacheHitRate,
      avgLatency,
      cost,
    }
  })
}

export function generateMockProviders(): ProviderMetrics[] {
  return PROVIDERS.map(p => ({
    id: p.name.toLowerCase(),
    name: p.name,
    status: randomItem(['healthy', 'healthy', 'healthy', 'degraded']) as 'healthy' | 'degraded',
    models: [...p.models],
    requests: randomInt(5000, 80000),
    avgLatency: randomInt(200, 600),
    cost: randomFloat(100, 5000),
    errors: randomInt(0, 50),
    errorRate: randomFloat(0, 0.02),
  }))
}

export function generateMockCacheMetrics(): CacheMetrics {
  return {
    totalEntries: randomInt(50000, 200000),
    memoryUsage: randomFloat(2.5, 15.5, 1),
    hitRate: randomFloat(0.65, 0.85),
    missRate: randomFloat(0.15, 0.35),
    evictions: randomInt(1000, 10000),
    invalidations: randomInt(50, 500),
    avgSimilarity: randomFloat(0.82, 0.95),
    avgTokensSaved: randomInt(1500, 4000),
    layers: {
      L1: {
        hitRate: randomFloat(0.25, 0.4),
        requests: randomInt(10000, 50000),
        tokensSaved: randomInt(500000, 2000000),
        latencySaved: randomInt(50, 150),
        entries: randomInt(10000, 50000),
      },
      L2: {
        hitRate: randomFloat(0.2, 0.35),
        requests: randomInt(15000, 60000),
        tokensSaved: randomInt(800000, 3000000),
        latencySaved: randomInt(100, 300),
        entries: randomInt(20000, 80000),
      },
      L3: {
        hitRate: randomFloat(0.08, 0.18),
        requests: randomInt(5000, 25000),
        tokensSaved: randomInt(200000, 1000000),
        latencySaved: randomInt(200, 500),
        entries: randomInt(5000, 30000),
      },
    },
  }
}

export function generateMockCacheEntries(count: number): CacheEntry[] {
  const entries: CacheEntry[] = []
  const statuses: Array<'active' | 'expired' | 'evicted' | 'invalidated'> = ['active', 'active', 'active', 'active', 'expired', 'evicted']

  for (let i = 0; i < count; i++) {
    const layer = randomItem(CACHE_LAYERS)
    const model = randomItem(MODELS)
    const createdAt = new Date(Date.now() - randomInt(0, 30 * 24 * 60 * 60 * 1000))
    const ttl = layer === 'L1' ? 3600 : layer === 'L2' ? 86400 : 604800
    const expiresAt = new Date(createdAt.getTime() + ttl * 1000)

    entries.push({
      key: generateCacheKey(),
      layer,
      model,
      similarity: layer === 'L1' ? null : randomFloat(0.75, 0.99),
      tokensSaved: randomInt(500, 5000),
      createdAt: createdAt.toISOString(),
      expiresAt: expiresAt.toISOString(),
      status: randomItem(statuses),
    })
  }

  return entries.sort((a, b) => new Date(b.createdAt).getTime() - new Date(a.createdAt).getTime())
}

export function generateMockOverviewMetrics(): OverviewMetrics {
  const requests = randomInt(100000, 500000)
  const hitRate = randomFloat(0.65, 0.85)
  const tokensSaved = randomInt(2000000, 10000000)
  const cost = randomFloat(50, 500)
  const latency = randomInt(200, 600)

  return {
    requests: {
      label: 'Requests',
      value: requests.toLocaleString(),
      trend: randomFloat(-5, 20),
      trendLabel: 'vs last period',
    },
    cacheHitRate: {
      label: 'Cache Hit Rate',
      value: `${(hitRate * 100).toFixed(1)}%`,
      trend: randomFloat(-2, 8),
      trendLabel: 'vs last period',
    },
    tokensSaved: {
      label: 'Tokens Saved',
      value: `${(tokensSaved / 1000000).toFixed(2)}M`,
      trend: randomFloat(-10, 25),
      trendLabel: `≈ $${(tokensSaved / 1000000 * 6.5).toFixed(2)}`,
    },
    estimatedCost: {
      label: 'Est. Cost',
      value: `$${cost.toFixed(2)}`,
      trend: randomFloat(-15, 10),
      trendLabel: 'vs last period',
    },
    avgLatency: {
      label: 'Avg Latency',
      value: `${latency}ms`,
      trend: randomFloat(-20, 5),
      trendLabel: 'vs last period',
    },
  }
}

export function generateMockTimeSeries(metric: 'requests' | 'tokens' | 'cost' | 'latency', range: '1h' | '24h' | '7d' | '30d'): TimeSeriesPoint[] {
  const points: TimeSeriesPoint[] = []
  const now = new Date()
  let interval: number
  let count: number

  switch (range) {
    case '1h':
      interval = 60 * 1000 // 1 minute
      count = 60
      break
    case '24h':
      interval = 15 * 60 * 1000 // 15 minutes
      count = 96
      break
    case '7d':
      interval = 60 * 60 * 1000 // 1 hour
      count = 168
      break
    case '30d':
      interval = 24 * 60 * 60 * 1000 // 1 day
      count = 30
      break
  }

  let baseValue = 0
  switch (metric) {
    case 'requests': baseValue = 100; break
    case 'tokens': baseValue = 50000; break
    case 'cost': baseValue = 10; break
    case 'latency': baseValue = 300; break
  }

  for (let i = count - 1; i >= 0; i--) {
    const timestamp = new Date(now.getTime() - i * interval)
    const variation = randomFloat(-0.3, 0.3)
    const trend = Math.sin(i * 0.1) * 0.2
    const value = Math.max(0, baseValue * (1 + variation + trend))

    points.push({
      timestamp: timestamp.toISOString(),
      value: Math.round(value * 100) / 100,
      label: timestamp.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' }),
    })
  }

  return points
}

export function generateMockEvents(count: number): DashboardEvent[] {
  const events: DashboardEvent[] = []
  const eventTypes: DashboardEvent['type'][] = [
    'RequestStarted',
    'RequestCompleted',
    'CacheHit',
    'CacheMiss',
    'CacheWrite',
    'ProviderRequest',
    'ProviderResponse',
  ]

  for (let i = 0; i < count; i++) {
    const type = randomItem(eventTypes)
    const requestId = generateRequestId()
    const timestamp = new Date(Date.now() - randomInt(0, 300000)).toISOString()

    const baseEvent = { id: `evt_${Math.random().toString(36).substring(2, 10)}`, type, timestamp, requestId }

    switch (type) {
      case 'RequestStarted':
        events.push({
          ...baseEvent,
          type: 'RequestStarted',
          payload: {
            model: randomItem(MODELS),
            provider: randomItem(PROVIDERS).name,
            endpoint: randomItem(ENDPOINTS),
            estimatedTokens: randomInt(1000, 5000),
          },
        })
        break
      case 'RequestCompleted':
        events.push({
          ...baseEvent,
          type: 'RequestCompleted',
          payload: generateMockRequests(1)[0],
        })
        break
      case 'CacheHit':
        events.push({
          ...baseEvent,
          type: 'CacheHit',
          payload: {
            layer: randomItem(CACHE_LAYERS),
            similarity: randomFloat(0.85, 0.99),
            tokensSaved: randomInt(1000, 5000),
            latencySaved: randomInt(100, 500),
          },
        })
        break
      case 'CacheMiss':
        events.push({
          ...baseEvent,
          type: 'CacheMiss',
          payload: {
            layer: randomItem(CACHE_LAYERS),
          },
        })
        break
      case 'CacheWrite':
        events.push({
          ...baseEvent,
          type: 'CacheWrite',
          payload: {
            layer: randomItem(CACHE_LAYERS),
            tokens: randomInt(1000, 5000),
          },
        })
        break
      case 'ProviderRequest':
        events.push({
          ...baseEvent,
          type: 'ProviderRequest',
          payload: {
            provider: randomItem(PROVIDERS).name,
            model: randomItem(MODELS),
            estimatedTokens: randomInt(1000, 5000),
          },
        })
        break
      case 'ProviderResponse':
        events.push({
          ...baseEvent,
          type: 'ProviderResponse',
          payload: {
            provider: randomItem(PROVIDERS).name,
            model: randomItem(MODELS),
            latency: randomInt(100, 1000),
            tokens: { input: randomInt(500, 3000), output: randomInt(50, 500), total: 0, cachedInput: 0 },
            cost: randomFloat(0.001, 0.05),
          },
        })
        break
    }
  }

  return events.sort((a, b) => new Date(b.timestamp).getTime() - new Date(a.timestamp).getTime())
}

export function generateMockHealthCheck(): HealthCheck {
  return {
    status: 'ok',
    services: {
      redis: 'connected',
      qdrant: 'connected',
      api: 'connected',
    },
    version: '1.0.4',
    uptime: randomInt(3600, 86400 * 30),
  }
}

// Pre-generated datasets
export const mockRequests = generateMockRequests(500)
export const mockModels = generateMockModels()
export const mockProviders = generateMockProviders()
export const mockCacheMetrics = generateMockCacheMetrics()
export const mockCacheEntries = generateMockCacheEntries(200)
export const mockOverviewMetrics = generateMockOverviewMetrics()
export const mockHealthCheck = generateMockHealthCheck()
export const mockEvents = generateMockEvents(100)