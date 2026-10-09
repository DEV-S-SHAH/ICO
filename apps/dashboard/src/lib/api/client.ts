// API client abstraction for the dashboard

import type {
  Request,
  ModelMetrics,
  ProviderMetrics,
  CacheMetrics,
  CacheEntry,
  OverviewMetrics,
  TimeSeriesPoint,
  HealthCheck,
  FilterState,
  PaginationState,
  SortState,
  ApiResponse,
  Settings,
  ProviderConfig,
} from '@/types'

// Configuration - using import.meta.env for Vite
const API_BASE_URL = import.meta.env.VITE_API_URL || 'http://localhost:8000'
const WS_URL = import.meta.env.VITE_WS_URL || 'ws://localhost:8000/ws'
const ENVIRONMENT = import.meta.env.VITE_ENVIRONMENT || 'development'

export interface ApiConfig {
  baseUrl: string
  wsUrl: string
  environment: 'development' | 'staging' | 'production'
  apiKey?: string
  timeout: number
}

export interface PlaygroundStreamPayload {
  model: string
  systemPrompt: string
  userPrompt: string
  temperature?: number
  topP?: number
  maxTokens?: number
  thinking?: boolean
}

export interface PlaygroundStreamHandlers {
  onStart?: (meta: { request_id?: string; model?: string }) => void
  onDelta?: (delta: { reasoning: string; content: string }) => void
  onDone?: (meta: { request_id?: string; model?: string; latency_ms?: number; reasoning_tokens?: number; output_tokens?: number }) => void
  onError?: (message: string) => void
}

class ApiClient {
  private config: ApiConfig
  private abortController: AbortController | null = null

  constructor(config: Partial<ApiConfig> = {}) {
    this.config = {
      baseUrl: config.baseUrl || API_BASE_URL,
      wsUrl: config.wsUrl || WS_URL,
      environment: config.environment || ENVIRONMENT,
      apiKey: config.apiKey,
      timeout: config.timeout || 10000,
    }
  }

  setApiKey(key: string) {
    this.config.apiKey = key
  }

  setEnvironment(env: 'development' | 'staging' | 'production') {
    this.config.environment = env
  }

  private getHeaders(): HeadersInit {
    const headers: Record<string, string> = {
      'Content-Type': 'application/json',
    }
    if (this.config.apiKey) {
      headers['X-API-Key'] = this.config.apiKey
    }
    return headers
  }

  private async fetch<T>(endpoint: string, options: RequestInit = {}): Promise<T> {
    const controller = new AbortController()
    this.abortController = controller

    const timeoutId = setTimeout(() => controller.abort(), this.config.timeout)

    try {
      const response = await fetch(`${this.config.baseUrl}${endpoint}`, {
        ...options,
        headers: {
          ...this.getHeaders(),
          ...options.headers,
        },
        signal: controller.signal,
      })

      clearTimeout(timeoutId)

      if (!response.ok) {
        const error = await response.json().catch(() => ({ message: response.statusText }))
        throw new Error(error.message || `HTTP ${response.status}`)
      }

      return response.json()
    } catch (error) {
      clearTimeout(timeoutId)
      if (error instanceof Error && error.name === 'AbortError') {
        throw new Error('Request timeout')
      }
      throw error
    }
  }

  cancel() {
    this.abortController?.abort()
  }

  // Health check
  async healthCheck(): Promise<HealthCheck> {
    return this.fetch<HealthCheck>('/v1/health')
  }

  // Overview metrics
  async getOverviewMetrics(): Promise<OverviewMetrics> {
    return this.fetch<OverviewMetrics>('/v1/metrics/overview')
  }

  // Requests
  async getRequests(
    filters: FilterState,
    pagination: PaginationState,
    sort: SortState
  ): Promise<ApiResponse<Request[]>> {
    const params = new URLSearchParams()
    Object.entries(filters).forEach(([key, value]) => {
      if (value !== 'all' && value !== '') params.append(key, String(value))
    })
    params.append('page', String(pagination.page))
    params.append('pageSize', String(pagination.pageSize))
    params.append('sortColumn', sort.column)
    params.append('sortDirection', sort.direction)

    return this.fetch<ApiResponse<Request[]>>(`/v1/requests?${params.toString()}`)
  }

  async getRequest(id: string): Promise<Request> {
    return this.fetch<Request>(`/v1/requests/${id}`)
  }

  // Models
  async getModels(): Promise<ModelMetrics[]> {
    return this.fetch<ModelMetrics[]>('/v1/models')
  }

  async getModel(id: string): Promise<ModelMetrics> {
    return this.fetch<ModelMetrics>(`/v1/models/${id}`)
  }

  // Providers
  async getProviders(): Promise<ProviderMetrics[]> {
    return this.fetch<ProviderMetrics[]>('/v1/providers')
  }

  async getProvider(id: string): Promise<ProviderMetrics> {
    return this.fetch<ProviderMetrics>(`/v1/providers/${id}`)
  }

  // Cache
  async getCacheMetrics(): Promise<CacheMetrics> {
    return this.fetch<CacheMetrics>('/v1/cache/metrics')
  }

  async getCacheEntries(
    filters: { layer?: string; model?: string; status?: string },
    pagination: PaginationState,
    sort: SortState
  ): Promise<ApiResponse<CacheEntry[]>> {
    const params = new URLSearchParams()
    Object.entries(filters).forEach(([key, value]) => {
      if (value) params.append(key, value)
    })
    params.append('page', String(pagination.page))
    params.append('pageSize', String(pagination.pageSize))
    params.append('sortColumn', sort.column)
    params.append('sortDirection', sort.direction)

    return this.fetch<ApiResponse<CacheEntry[]>>(`/v1/cache/entries?${params.toString()}`)
  }

  async invalidateCache(tenantId: string, filter?: Record<string, string>): Promise<{ l1Purged: number; l2Purged: number; l3Purged: number }> {
    return this.fetch('/v1/cache/invalidate', {
      method: 'POST',
      body: JSON.stringify({ tenant_id: tenantId, filter }),
    })
  }

  // Metrics / Time series
  async getTimeSeries(
    metric: 'requests' | 'tokens' | 'cost' | 'latency',
    range: '1h' | '24h' | '7d' | '30d'
  ): Promise<TimeSeriesPoint[]> {
    return this.fetch<TimeSeriesPoint[]>(`/v1/metrics/timeseries?metric=${metric}&range=${range}`)
  }

  // Settings
  async getSettings(): Promise<Settings> {
    return this.fetch<Settings>('/v1/settings')
  }

  async updateSettings(settings: Partial<Settings>): Promise<Settings> {
    return this.fetch<Settings>('/v1/settings', {
      method: 'PATCH',
      body: JSON.stringify(settings),
    })
  }

  // Playground
  async sendPlaygroundRequest(payload: {
    model: string
    provider: string
    endpoint: string
    systemPrompt: string
    userPrompt: string
    temperature?: number
    maxTokens?: number
  }): Promise<Request> {
    return this.fetch<Request>('/v1/playground', {
      method: 'POST',
      body: JSON.stringify(payload),
    })
  }

  // Streaming playground request (Server-Sent Events, token by token)
  async streamPlaygroundRequest(
    payload: PlaygroundStreamPayload,
    handlers: PlaygroundStreamHandlers = {},
    signal?: AbortSignal
  ): Promise<void> {
    const response = await fetch(`${this.config.baseUrl}/v1/playground/stream`, {
      method: 'POST',
      headers: this.getHeaders(),
      body: JSON.stringify(payload),
      signal,
    })

    if (!response.ok || !response.body) {
      const error = await response.json().catch(() => ({ detail: response.statusText }))
      throw new Error(error.detail || error.message || `HTTP ${response.status}`)
    }

    const reader = response.body.getReader()
    const decoder = new TextDecoder()
    let buffer = ''

    const handleEvent = (raw: string) => {
      const line = raw.trim()
      if (!line.startsWith('data:')) return
      const data = line.slice(5).trim()
      if (!data || data === '[DONE]') return
      let event: {
        type: string
        request_id?: string
        model?: string
        reasoning?: string
        content?: string
        error?: string
        latency_ms?: number
        reasoning_tokens?: number
        output_tokens?: number
      }
      try {
        event = JSON.parse(data)
      } catch {
        return
      }
      switch (event.type) {
        case 'start':
          handlers.onStart?.({ request_id: event.request_id, model: event.model })
          break
        case 'delta':
          handlers.onDelta?.({ reasoning: event.reasoning || '', content: event.content || '' })
          break
        case 'done':
          handlers.onDone?.({
            request_id: event.request_id,
            model: event.model,
            latency_ms: event.latency_ms,
            reasoning_tokens: event.reasoning_tokens,
            output_tokens: event.output_tokens,
          })
          break
        case 'error':
          handlers.onError?.(event.error || 'Streaming failed')
          break
      }
    }

    while (true) {
      const { done, value } = await reader.read()
      if (done) break
      buffer += decoder.decode(value, { stream: true })
      const parts = buffer.split('\n\n')
      buffer = parts.pop() ?? ''
      for (const part of parts) handleEvent(part)
    }
    if (buffer) handleEvent(buffer)
  }

  // WebSocket connection
  createWebSocket(): WebSocket {
    const ws = new WebSocket(`${this.config.wsUrl}?api_key=${this.config.apiKey}`)
    return ws
  }

  // SSE connection
  createEventSource(): EventSource {
    const url = new URL(`${this.config.baseUrl}/v1/events`)
    if (this.config.apiKey) {
      url.searchParams.append('api_key', this.config.apiKey)
    }
    return new EventSource(url.toString())
  }
}

// Singleton instance
export const apiClient = new ApiClient()

export function getApiClient(): ApiClient {
  return apiClient
}