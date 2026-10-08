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

// Mock API client for demo mode
export class MockApiClient {
  private delay(ms: number): Promise<void> {
    return new Promise(resolve => setTimeout(resolve, ms))
  }

  async healthCheck(): Promise<HealthCheck> {
    await this.delay(100)
    const { mockHealthCheck } = await import('@/data/mock')
    return mockHealthCheck
  }

  async getOverviewMetrics(): Promise<OverviewMetrics> {
    await this.delay(150)
    const { mockOverviewMetrics } = await import('@/data/mock')
    return mockOverviewMetrics
  }

  async getRequests(
    filters: FilterState,
    pagination: PaginationState,
    sort: SortState
  ): Promise<ApiResponse<Request[]>> {
    await this.delay(200)
    const { mockRequests } = await import('@/data/mock')
    let filtered = [...mockRequests]

    // Apply filters
    if (filters.status !== 'all') {
      filtered = filtered.filter(r => r.status === filters.status)
    }
    if (filters.model !== 'all') {
      filtered = filtered.filter(r => r.model === filters.model)
    }
    if (filters.provider !== 'all') {
      filtered = filtered.filter(r => r.provider === filters.provider)
    }
    if (filters.cache !== 'all') {
      filtered = filtered.filter(r => r.cache.status === filters.cache)
    }
    if (filters.endpoint !== 'all') {
      filtered = filtered.filter(r => r.endpoint === filters.endpoint)
    }
    if (filters.search) {
      const search = filters.search.toLowerCase()
      filtered = filtered.filter(r =>
        r.id.toLowerCase().includes(search) ||
        r.model.toLowerCase().includes(search) ||
        r.endpoint.toLowerCase().includes(search)
      )
    }

    // Apply sorting
    filtered.sort((a, b) => {
      const aVal = a[sort.column as keyof Request]
      const bVal = b[sort.column as keyof Request]
      if (aVal < bVal) return sort.direction === 'asc' ? -1 : 1
      if (aVal > bVal) return sort.direction === 'asc' ? 1 : -1
      return 0
    })

    // Apply pagination
    const start = (pagination.page - 1) * pagination.pageSize
    const end = start + pagination.pageSize
    const paginated = filtered.slice(start, end)

    return {
      data: paginated,
      meta: {
        page: pagination.page,
        pageSize: pagination.pageSize,
        total: filtered.length,
      },
    }
  }

  async getRequest(id: string): Promise<Request> {
    await this.delay(100)
    const { mockRequests } = await import('@/data/mock')
    const request = mockRequests.find(r => r.id === id)
    if (!request) throw new Error('Request not found')
    return request
  }

  async getModels(): Promise<ModelMetrics[]> {
    await this.delay(150)
    const { mockModels } = await import('@/data/mock')
    return mockModels
  }

  async getModel(id: string): Promise<ModelMetrics> {
    await this.delay(100)
    const { mockModels } = await import('@/data/mock')
    const model = mockModels.find(m => m.id === id)
    if (!model) throw new Error('Model not found')
    return model
  }

  async getProviders(): Promise<ProviderMetrics[]> {
    await this.delay(150)
    const { mockProviders } = await import('@/data/mock')
    return mockProviders
  }

  async getProvider(id: string): Promise<ProviderMetrics> {
    await this.delay(100)
    const { mockProviders } = await import('@/data/mock')
    const provider = mockProviders.find(p => p.id === id)
    if (!provider) throw new Error('Provider not found')
    return provider
  }

  async getCacheMetrics(): Promise<CacheMetrics> {
    await this.delay(150)
    const { mockCacheMetrics } = await import('@/data/mock')
    return mockCacheMetrics
  }

  async getCacheEntries(
    filters: { layer?: string; model?: string; status?: string },
    pagination: PaginationState,
    sort: SortState
  ): Promise<ApiResponse<CacheEntry[]>> {
    await this.delay(200)
    const { mockCacheEntries } = await import('@/data/mock')
    let filtered = [...mockCacheEntries]

    if (filters.layer) {
      filtered = filtered.filter(e => e.layer === filters.layer)
    }
    if (filters.model) {
      filtered = filtered.filter(e => e.model === filters.model)
    }
    if (filters.status) {
      filtered = filtered.filter(e => e.status === filters.status)
    }

    filtered.sort((a, b) => {
      const aVal = a[sort.column as keyof CacheEntry]
      const bVal = b[sort.column as keyof CacheEntry]
      if (aVal < bVal) return sort.direction === 'asc' ? -1 : 1
      if (aVal > bVal) return sort.direction === 'asc' ? 1 : -1
      return 0
    })

    const start = (pagination.page - 1) * pagination.pageSize
    const end = start + pagination.pageSize
    const paginated = filtered.slice(start, end)

    return {
      data: paginated,
      meta: {
        page: pagination.page,
        pageSize: pagination.pageSize,
        total: filtered.length,
      },
    }
  }

  async invalidateCache(tenantId: string, filter?: Record<string, string>): Promise<{ l1Purged: number; l2Purged: number; l3Purged: number }> {
    await this.delay(500)
    return { l1Purged: 123, l2Purged: 456, l3Purged: 78 }
  }

  async getTimeSeries(
    metric: 'requests' | 'tokens' | 'cost' | 'latency',
    range: '1h' | '24h' | '7d' | '30d'
  ): Promise<TimeSeriesPoint[]> {
    await this.delay(200)
    const { generateMockTimeSeries } = await import('@/data/mock')
    return generateMockTimeSeries(metric, range)
  }

  async getSettings(): Promise<Settings> {
    await this.delay(100)
    // Return default settings
    return {
      general: { appName: 'Synapse', defaultTenant: 'default', defaultModel: 'claude-sonnet-4.6' },
      connection: { apiUrl: 'http://localhost:8000', wsUrl: 'ws://localhost:8000/ws', timeout: 10000, retryAttempts: 3 },
      providers: [],
      cache: { l1Enabled: true, l2Enabled: true, l3Enabled: true, l1Ttl: 3600, l2Ttl: 86400, l3Ttl: 604800, similarityThreshold: 0.85 },
      events: { enabled: true, transport: 'websocket', pollingInterval: 5000 },
      appearance: { theme: 'dark', compactMode: false, animations: true },
      api: { apiKeys: {}, rateLimit: 1000 },
      advanced: { debugMode: false, logLevel: 'info', telemetryEnabled: true },
    }
  }

  async updateSettings(settings: Partial<Settings>): Promise<Settings> {
    await this.delay(200)
    const current = await this.getSettings()
    return { ...current, ...settings }
  }

  async sendPlaygroundRequest(payload: {
    model: string
    provider: string
    endpoint: string
    systemPrompt: string
    userPrompt: string
    temperature?: number
    maxTokens?: number
  }): Promise<Request> {
    await this.delay(1500)
    const { mockRequests } = await import('@/data/mock')
    // Return a mock request with the playground data
    const request = mockRequests[0]
    return {
      ...request,
      model: payload.model,
      provider: payload.provider,
      endpoint: payload.endpoint,
      requestBody: {
        model: payload.model,
        messages: [
          { role: 'system', content: payload.systemPrompt },
          { role: 'user', content: payload.userPrompt },
        ],
        temperature: payload.temperature ?? 0.7,
        max_tokens: payload.maxTokens ?? 1000,
      },
    }
  }

  async createWebSocket(): Promise<WebSocket> {
    // Return a mock WebSocket that simulates events
    const mockWs = {
      readyState: WebSocket.OPEN,
      onopen: null as ((event: Event) => void) | null,
      onmessage: null as ((event: MessageEvent) => void) | null,
      onclose: null as ((event: CloseEvent) => void) | null,
      onerror: null as ((event: Event) => void) | null,
      send: (data: string) => {},
      close: () => {
        mockWs.readyState = WebSocket.CLOSED
        mockWs.onclose?.(new CloseEvent('close'))
      },
    } as unknown as WebSocket

    // Simulate connection
    setTimeout(() => mockWs.onopen?.(new Event('open')), 100)

    // Simulate periodic events
    const { generateMockEvents } = await import('@/data/mock')
    const events = generateMockEvents(20)
    let index = 0
    const interval = setInterval(() => {
      if (index < events.length) {
        mockWs.onmessage?.(new MessageEvent('message', { data: JSON.stringify(events[index]) }))
        index++
      } else {
        clearInterval(interval)
      }
    }, 2000)

    return mockWs
  }

  async createEventSource(): Promise<EventSource> {
    // Return a mock EventSource
    const mockEs = {
      readyState: EventSource.OPEN,
      onopen: null as ((event: Event) => void) | null,
      onmessage: null as ((event: MessageEvent) => void) | null,
      onerror: null as ((event: Event) => void) | null,
      close: () => {
        mockEs.readyState = EventSource.CLOSED
      },
    } as unknown as EventSource

    setTimeout(() => mockEs.onopen?.(new Event('open')), 100)

    const { generateMockEvents } = await import('@/data/mock')
    const events = generateMockEvents(20)
    let index = 0
    const interval = setInterval(() => {
      if (index < events.length) {
        mockEs.onmessage?.(new MessageEvent('message', { data: JSON.stringify(events[index]) }))
        index++
      } else {
        clearInterval(interval)
      }
    }, 2000)

    return mockEs
  }
}

export const mockApiClient = new MockApiClient()

// Factory to get the appropriate client based on mode
export function getApiClient(useMock: boolean): ApiClient | MockApiClient {
  return useMock ? mockApiClient : apiClient
}