// Core domain types for the Synapse dashboard

export type Environment = 'development' | 'staging' | 'production'

export type CacheLayer = 'L0' | 'L0a' | 'L0b' | 'L1' | 'L2' | 'L3' | 'L4' | 'L5' | 'LLM' | string
export type CacheStatus = 'HIT' | 'MISS' | 'SKIPPED' | 'WRITE'
export type RequestStatus = 'OK' | 'ERROR' | 'TIMEOUT' | 'RATE_LIMITED' | 'PENDING'

export interface CacheDecision {
  layer: CacheLayer
  status: CacheStatus
  similarity?: number
  tokensSaved?: number
  latencySaved?: number
  duration?: number
}

export interface TokenUsage {
  input: number
  output: number
  total: number
  cachedInput: number
}

export interface CostBreakdown {
  input: number
  output: number
  total: number
  saved: number
}

export interface RequestTraceNode {
  id: string
  name: string
  duration: number
  status: 'success' | 'error' | 'pending'
  result?: string
  details?: Record<string, unknown>
  children?: RequestTraceNode[]
}

export interface Request {
  id: string
  timestamp: string
  model: string
  provider: string
  endpoint: string
  tokens: TokenUsage
  cache: {
    layer: CacheLayer | null
    status: CacheStatus
    similarity?: number
    tokensSaved: number
    latencySaved: number
  }
  latency: number
  cost: CostBreakdown
  status: RequestStatus
  query?: string
  trace?: RequestTraceNode
  requestBody?: unknown
  responseBody?: unknown
  cacheDecision?: CacheDecision[]
}

export interface ModelMetrics {
  id: string
  name: string
  provider: string
  requests: number
  inputTokens: number
  outputTokens: number
  cachedTokens: number
  cacheHitRate: number
  avgLatency: number
  cost: number
}

export interface ProviderMetrics {
  id: string
  name: string
  status: 'healthy' | 'degraded' | 'down'
  models: string[]
  requests: number
  avgLatency: number
  cost: number
  errors: number
  errorRate: number
}

export interface CacheMetrics {
  totalEntries: number
  memoryUsage: number
  hitRate: number
  missRate: number
  evictions: number
  invalidations: number
  avgSimilarity: number
  avgTokensSaved: number
  layers: {
    L1?: CacheLayerMetrics
    L2?: CacheLayerMetrics
    L3?: CacheLayerMetrics
    [key: string]: CacheLayerMetrics | undefined
  }
}

export interface CacheLayerMetrics {
  hitRate: number
  requests: number
  tokensSaved: number
  latencySaved: number
  entries: number
}

export interface CacheEntry {
  key: string
  layer: CacheLayer
  model: string
  similarity: number | null
  tokensSaved: number
  createdAt: string
  expiresAt: string
  status: 'active' | 'expired' | 'evicted' | 'invalidated'
}

export interface TimeSeriesPoint {
  timestamp: string
  value: number
  label?: string
}

export interface MetricCardData {
  label: string
  value: string | number
  trend?: number
  trendLabel?: string
  unit?: string
}

export interface OverviewMetrics {
  requests: MetricCardData
  cacheHitRate: MetricCardData
  tokensSaved: MetricCardData
  estimatedCost: MetricCardData
  avgLatency: MetricCardData
}

export interface FilterState {
  status: RequestStatus | 'all'
  model: string | 'all'
  provider: string | 'all'
  cache: CacheStatus | 'all'
  endpoint: string | 'all'
  timeRange: TimeRange
  search: string
}

export type TimeRange = '1h' | '24h' | '7d' | '30d'

export interface PaginationState {
  page: number
  pageSize: number
  total: number
}

export interface SortState {
  column: string
  direction: 'asc' | 'desc'
}

// Event types for real-time updates
export type EventType =
  | 'RequestStarted'
  | 'RequestCompleted'
  | 'CacheHit'
  | 'CacheMiss'
  | 'CacheWrite'
  | 'CacheInvalidation'
  | 'ProviderRequest'
  | 'ProviderResponse'
  | 'Error'

export interface BaseEvent {
  id: string
  type: EventType
  timestamp: string
  requestId: string
}

export interface RequestStartedEvent extends BaseEvent {
  type: 'RequestStarted'
  payload: {
    model: string
    provider: string
    endpoint: string
    estimatedTokens: number
  }
}

export interface RequestCompletedEvent extends BaseEvent {
  type: 'RequestCompleted'
  payload: Request
}

export interface CacheHitEvent extends BaseEvent {
  type: 'CacheHit'
  payload: {
    layer: CacheLayer
    similarity: number
    tokensSaved: number
    latencySaved: number
  }
}

export interface CacheMissEvent extends BaseEvent {
  type: 'CacheMiss'
  payload: {
    layer: CacheLayer
  }
}

export interface CacheWriteEvent extends BaseEvent {
  type: 'CacheWrite'
  payload: {
    layer: CacheLayer
    tokens: number
  }
}

export interface CacheInvalidationEvent extends BaseEvent {
  type: 'CacheInvalidation'
  payload: {
    layer: CacheLayer
    count: number
    reason: string
  }
}

export interface ProviderRequestEvent extends BaseEvent {
  type: 'ProviderRequest'
  payload: {
    provider: string
    model: string
    estimatedTokens: number
  }
}

export interface ProviderResponseEvent extends BaseEvent {
  type: 'ProviderResponse'
  payload: {
    provider: string
    model: string
    latency: number
    tokens: TokenUsage
    cost: number
  }
}

export interface ErrorEvent extends BaseEvent {
  type: 'Error'
  payload: {
    message: string
    code: string
    recoverable: boolean
  }
}

export type DashboardEvent =
  | RequestStartedEvent
  | RequestCompletedEvent
  | CacheHitEvent
  | CacheMissEvent
  | CacheWriteEvent
  | CacheInvalidationEvent
  | ProviderRequestEvent
  | ProviderResponseEvent
  | ErrorEvent

// API Response types
export interface ApiResponse<T> {
  data: T
  meta?: {
    page: number
    pageSize: number
    total: number
  }
}

export interface HealthCheck {
  status: 'ok' | 'degraded' | 'down'
  services: {
    redis: 'connected' | 'disconnected'
    qdrant: 'connected' | 'disconnected'
    api: 'connected' | 'disconnected'
  }
  version: string
  uptime: number
}

// Settings types
export interface Settings {
  general: {
    appName: string
    defaultTenant: string
    defaultModel: string
  }
  connection: {
    apiUrl: string
    wsUrl: string
    timeout: number
    retryAttempts: number
  }
  providers: ProviderConfig[]
  cache: {
    l1Enabled: boolean
    l2Enabled: boolean
    l3Enabled: boolean
    l1Ttl: number
    l2Ttl: number
    l3Ttl: number
    similarityThreshold: number
  }
  events: {
    enabled: boolean
    transport: 'websocket' | 'sse' | 'polling'
    pollingInterval: number
  }
  appearance: {
    theme: 'dark' | 'light' | 'system'
    compactMode: boolean
    animations: boolean
  }
  api: {
    apiKeys: Record<string, string>
    rateLimit: number
  }
  advanced: {
    debugMode: boolean
    logLevel: 'debug' | 'info' | 'warn' | 'error'
    telemetryEnabled: boolean
  }
}

export interface ProviderConfig {
  id: string
  name: string
  type: 'openai' | 'anthropic' | 'ollama' | 'openrouter' | 'nim' | 'custom'
  baseUrl: string
  apiKey: string
  models: string[]
  enabled: boolean
  priority: number
}