// Global state management using Zustand

import { create } from 'zustand'
import { persist } from 'zustand/middleware'
import type {
  FilterState,
  PaginationState,
  SortState,
  TimeRange,
  Environment,
  Settings,
  Request,
  ModelMetrics,
  ProviderMetrics,
  CacheMetrics,
  OverviewMetrics,
} from '@/types'

// Default states
const defaultFilters: FilterState = {
  status: 'all',
  model: 'all',
  provider: 'all',
  cache: 'all',
  endpoint: 'all',
  timeRange: '24h',
  search: '',
}

const defaultPagination: PaginationState = {
  page: 1,
  pageSize: 25,
  total: 0,
}

const defaultSort: SortState = {
  column: 'timestamp',
  direction: 'desc',
}

interface UIState {
  // Sidebar
  sidebarCollapsed: boolean
  toggleSidebar: () => void
  setSidebarCollapsed: (collapsed: boolean) => void

  // Header
  environment: Environment
  setEnvironment: (env: Environment) => void

  // Theme
  theme: 'dark' | 'light' | 'system'
  setTheme: (theme: 'dark' | 'light' | 'system') => void

  // Demo/Live mode
  demoMode: boolean
  setDemoMode: (enabled: boolean) => void

  // Connection status
  connected: boolean
  setConnected: (connected: boolean) => void

  // Incremented on every real-time backend event; pages depend on it to re-fetch
  liveTick: number
  bumpLiveTick: () => void

  // Modals/Drawers
  requestDetailId: string | null
  openRequestDetail: (id: string) => void
  closeRequestDetail: () => void

  // Live incoming event
  latestLiveRequest: any | null
  setLatestLiveRequest: (req: any) => void

  cacheDetailKey: string | null
  openCacheDetail: (key: string) => void
  closeCacheDetail: () => void

  // Notifications
  notifications: Array<{ id: string; type: 'success' | 'error' | 'warning' | 'info'; message: string }>
  addNotification: (notification: Omit<UIState['notifications'][0], 'id'>) => void
  removeNotification: (id: string) => void
}

export const useUIStore = create<UIState>()(
  persist(
    (set) => ({
      sidebarCollapsed: false,
      toggleSidebar: () => set(state => ({ sidebarCollapsed: !state.sidebarCollapsed })),
      setSidebarCollapsed: (collapsed) => set({ sidebarCollapsed: collapsed }),

      environment: 'development',
      setEnvironment: (env) => set({ environment: env }),

      theme: 'dark',
      setTheme: (theme) => set({ theme }),

      demoMode: import.meta.env.VITE_ENABLE_DEMO_MODE === 'true',
      setDemoMode: (enabled) => set({ demoMode: enabled }),

      connected: false,
      setConnected: (connected) => set({ connected }),

      liveTick: 0,
      bumpLiveTick: () => set(state => ({ liveTick: state.liveTick + 1 })),

      latestLiveRequest: null,
      setLatestLiveRequest: (req) => set({ latestLiveRequest: req }),

      requestDetailId: null,
      openRequestDetail: (id) => set({ requestDetailId: id }),
      closeRequestDetail: () => set({ requestDetailId: null }),

      cacheDetailKey: null,
      openCacheDetail: (key) => set({ cacheDetailKey: key }),
      closeCacheDetail: () => set({ cacheDetailKey: null }),

      notifications: [],
      addNotification: (notification) =>
        set(state => ({
          notifications: [...state.notifications, { ...notification, id: Math.random().toString(36).slice(2) }],
        })),
      removeNotification: (id) =>
        set(state => ({
          notifications: state.notifications.filter(n => n.id !== id),
        })),
    }),
    {
      name: 'synapse-ui-v3',
      partialize: (state) => ({
        environment: state.environment,
        theme: state.theme,
        demoMode: state.demoMode,
      }),
    }
  )
)

interface DataState {
  // Requests
  requests: Request[]
  requestsFilters: FilterState
  requestsPagination: PaginationState
  requestsSort: SortState
  setRequests: (requests: Request[]) => void
  setRequestsFilters: (filters: Partial<FilterState>) => void
  setRequestsPagination: (pagination: Partial<PaginationState>) => void
  setRequestsSort: (sort: SortState) => void
  resetRequestsFilters: () => void

  // Models
  models: ModelMetrics[]
  setModels: (models: ModelMetrics[]) => void

  // Providers
  providers: ProviderMetrics[]
  setProviders: (providers: ProviderMetrics[]) => void

  // Cache
  cacheMetrics: CacheMetrics | null
  setCacheMetrics: (metrics: CacheMetrics) => void
  cacheEntries: Array<{ key: string; layer: string; model: string; similarity: number | null; tokensSaved: number; createdAt: string; expiresAt: string; status: string }>
  setCacheEntries: (entries: DataState['cacheEntries']) => void
  cacheFilters: { layer?: string; model?: string; status?: string }
  setCacheFilters: (filters: DataState['cacheFilters']) => void
  cachePagination: PaginationState
  setCachePagination: (pagination: Partial<PaginationState>) => void
  cacheSort: SortState
  setCacheSort: (sort: SortState) => void

  // Overview
  overviewMetrics: OverviewMetrics | null
  setOverviewMetrics: (metrics: OverviewMetrics) => void

  // Time series
  timeSeriesData: Record<string, Array<{ timestamp: string; value: number; label?: string }>>
  setTimeSeriesData: (key: string, data: Array<{ timestamp: string; value: number; label?: string }>) => void

  // Health
  healthCheck: { status: string; services: Record<string, string>; version: string; uptime: number } | null
  setHealthCheck: (health: DataState['healthCheck']) => void

  // Settings
  settings: Settings | null
  setSettings: (settings: Settings) => void
}

export const useDataStore = create<DataState>((set) => ({
  requests: [],
  requestsFilters: defaultFilters,
  requestsPagination: defaultPagination,
  requestsSort: defaultSort,
  setRequests: (requests) => set({ requests }),
  setRequestsFilters: (filters) => set(state => ({ requestsFilters: { ...state.requestsFilters, ...filters }, requestsPagination: { ...state.requestsPagination, page: 1 } })),
  setRequestsPagination: (pagination) => set(state => ({ requestsPagination: { ...state.requestsPagination, ...pagination } })),
  setRequestsSort: (sort) => set({ requestsSort: sort }),
  resetRequestsFilters: () => set({ requestsFilters: defaultFilters, requestsPagination: { ...defaultPagination } }),

  models: [],
  setModels: (models) => set({ models }),

  providers: [],
  setProviders: (providers) => set({ providers }),

  cacheMetrics: null,
  setCacheMetrics: (metrics) => set({ cacheMetrics: metrics }),
  cacheEntries: [],
  setCacheEntries: (entries) => set({ cacheEntries: entries }),
  cacheFilters: {},
  setCacheFilters: (filters) => set({ cacheFilters: filters, cachePagination: { ...defaultPagination, page: 1 } }),
  cachePagination: defaultPagination,
  setCachePagination: (pagination) => set(state => ({ cachePagination: { ...state.cachePagination, ...pagination } })),
  cacheSort: { column: 'createdAt', direction: 'desc' },
  setCacheSort: (sort) => set({ cacheSort: sort }),

  overviewMetrics: null,
  setOverviewMetrics: (metrics) => set({ overviewMetrics: metrics }),

  timeSeriesData: {},
  setTimeSeriesData: (key, data) => set(state => ({ timeSeriesData: { ...state.timeSeriesData, [key]: data } })),

  healthCheck: null,
  setHealthCheck: (health) => set({ healthCheck: health }),

  settings: null,
  setSettings: (settings) => set({ settings }),
}))

// Selection state for tables
interface SelectionState {
  selectedRequestIds: Set<string>
  toggleRequestSelection: (id: string) => void
  selectAllRequests: (ids: string[]) => void
  clearRequestSelection: () => void
  selectedCacheKeys: Set<string>
  toggleCacheSelection: (key: string) => void
  selectAllCache: (keys: string[]) => void
  clearCacheSelection: () => void
}

export const useSelectionStore = create<SelectionState>((set) => ({
  selectedRequestIds: new Set(),
  toggleRequestSelection: (id) => set(state => {
    const newSet = new Set(state.selectedRequestIds)
    if (newSet.has(id)) newSet.delete(id)
    else newSet.add(id)
    return { selectedRequestIds: newSet }
  }),
  selectAllRequests: (ids) => set({ selectedRequestIds: new Set(ids) }),
  clearRequestSelection: () => set({ selectedRequestIds: new Set() }),

  selectedCacheKeys: new Set(),
  toggleCacheSelection: (key) => set(state => {
    const newSet = new Set(state.selectedCacheKeys)
    if (newSet.has(key)) newSet.delete(key)
    else newSet.add(key)
    return { selectedCacheKeys: newSet }
  }),
  selectAllCache: (keys) => set({ selectedCacheKeys: new Set(keys) }),
  clearCacheSelection: () => set({ selectedCacheKeys: new Set() }),
}))

// Playground state
interface PlaygroundState {
  model: string
  provider: string
  endpoint: string
  systemPrompt: string
  userPrompt: string
  temperature: number
  maxTokens: number
  response: Request | null
  loading: boolean
  error: string | null
  setModel: (model: string) => void
  setProvider: (provider: string) => void
  setEndpoint: (endpoint: string) => void
  setSystemPrompt: (prompt: string) => void
  setUserPrompt: (prompt: string) => void
  setTemperature: (temp: number) => void
  setMaxTokens: (tokens: number) => void
  setResponse: (response: Request | null) => void
  setLoading: (loading: boolean) => void
  setError: (error: string | null) => void
  reset: () => void
}

export const usePlaygroundStore = create<PlaygroundState>((set) => ({
  model: 'claude-sonnet-4.6',
  provider: 'Anthropic',
  endpoint: '/v1/messages',
  systemPrompt: 'You are a helpful assistant.',
  userPrompt: '',
  temperature: 0.7,
  maxTokens: 1000,
  response: null,
  loading: false,
  error: null,
  setModel: (model) => set({ model }),
  setProvider: (provider) => set({ provider }),
  setEndpoint: (endpoint) => set({ endpoint }),
  setSystemPrompt: (prompt) => set({ systemPrompt: prompt }),
  setUserPrompt: (prompt) => set({ userPrompt: prompt }),
  setTemperature: (temp) => set({ temperature: temp }),
  setMaxTokens: (tokens) => set({ maxTokens: tokens }),
  setResponse: (response) => set({ response, loading: false }),
  setLoading: (loading) => set({ loading }),
  setError: (error) => set({ error, loading: false }),
  reset: () => set({
    model: 'claude-sonnet-4.6',
    provider: 'Anthropic',
    endpoint: '/v1/messages',
    systemPrompt: 'You are a helpful assistant.',
    userPrompt: '',
    temperature: 0.7,
    maxTokens: 1000,
    response: null,
    loading: false,
    error: null,
  }),
}))