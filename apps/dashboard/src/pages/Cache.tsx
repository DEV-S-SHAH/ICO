// Cache Page

import { useEffect, useState } from 'react'
import {
  Database,
  RefreshCw,
  Filter,
  Search,
  ChevronLeft,
  ChevronRight,
  Download,
  BarChart3,
  PieChart,
  ChevronUp,
  ChevronDown,
} from 'lucide-react'
import { cn } from '@/components/common'
import { formatNumber, formatPercent, formatBytes, formatRelativeTime, formatDuration } from '@/lib/formatters'
import {
  Button,
  Input,
  Select,
  Badge,
  Card,
  CardContent,
  Divider,
  EmptyState,
  LoadingSkeleton,
  Tabs,
  TabsList,
  TabsTrigger,
  TabsContent,
} from '@/components/common'
import { CacheLayerMetric, TotalCacheHitRate } from '@/components/metrics'
import { CachePerformanceChart, ModelComparisonChart } from '@/components/charts'
import { useUIStore, useDataStore } from '@/lib/stores'
import { getApiClient } from '@/lib/api/client'
import { mockCacheMetrics, mockCacheEntries } from '@/data/mock'
import type { CacheMetrics, CacheEntry, PaginationState, SortState } from '@/types'

const PAGE_SIZES = [25, 50, 100, 200]

const LAYER_OPTIONS = [
  { value: '', label: 'All Layers' },
  { value: 'L1', label: 'L1 Exact' },
  { value: 'L2', label: 'L2 Semantic' },
  { value: 'L3', label: 'L3 Context' },
]

const STATUS_OPTIONS = [
  { value: '', label: 'All Status' },
  { value: 'active', label: 'Active' },
  { value: 'expired', label: 'Expired' },
  { value: 'evicted', label: 'Evicted' },
  { value: 'invalidated', label: 'Invalidated' },
]

export function Cache() {
  const { demoMode, liveTick } = useUIStore()
  const {
    cacheMetrics,
    setCacheMetrics,
    cacheEntries,
    setCacheEntries,
    cacheFilters,
    setCacheFilters,
    cachePagination,
    setCachePagination,
    cacheSort,
    setCacheSort,
  } = useDataStore()

  const [loading, setLoading] = useState(false)
  const [activeTab, setActiveTab] = useState<'overview' | 'entries' | 'analytics'>('overview')

  // Load cache metrics (mock only in demo mode)
  useEffect(() => {
    async function loadCacheMetrics() {
      if (liveTick === 0 || demoMode) setLoading(true)
      try {
        const api = getApiClient(demoMode)
        const metrics = await api.getCacheMetrics()
        setCacheMetrics(metrics)
      } catch {
        if (demoMode) setCacheMetrics(mockCacheMetrics)
      } finally {
        setLoading(false)
      }
    }
    loadCacheMetrics()
  }, [demoMode, liveTick, setCacheMetrics])

  // Load cache entries
  useEffect(() => {
    async function loadCacheEntries() {
      if (liveTick === 0 || demoMode) setLoading(true)
      try {
        const api = getApiClient(demoMode)
        const response = await api.getCacheEntries(cacheFilters, cachePagination, cacheSort)
        setCacheEntries(response.data)
        setCachePagination({ total: response.meta?.total || 0 })
      } catch {
        if (!demoMode) return
        // Demo mode only: client-side filtering with mock data
        let filtered = [...mockCacheEntries]
        if (cacheFilters.layer) filtered = filtered.filter(e => e.layer === cacheFilters.layer)
        if (cacheFilters.model) filtered = filtered.filter(e => e.model === cacheFilters.model)
        if (cacheFilters.status) filtered = filtered.filter(e => e.status === cacheFilters.status)
        
        filtered.sort((a, b) => {
          const aVal = a[cacheSort.column as keyof CacheEntry]
          const bVal = b[cacheSort.column as keyof CacheEntry]
          if (aVal < bVal) return cacheSort.direction === 'asc' ? -1 : 1
          if (aVal > bVal) return cacheSort.direction === 'asc' ? 1 : -1
          return 0
        })
        
        const start = (cachePagination.page - 1) * cachePagination.pageSize
        setCacheEntries(filtered.slice(start, start + cachePagination.pageSize))
        setCachePagination({ total: filtered.length })
      } finally {
        setLoading(false)
      }
    }
    loadCacheEntries()
  }, [demoMode, liveTick, cacheFilters, cachePagination.page, cachePagination.pageSize, cacheSort, setCacheEntries, setCachePagination])

  const metrics = cacheMetrics
  const totalHitRate = metrics?.hitRate || 0
  const l1Rate = metrics?.layers.L1.hitRate || 0
  const l2Rate = metrics?.layers.L2.hitRate || 0
  const l3Rate = metrics?.layers.L3.hitRate || 0

  // Handle sort
  const handleSort = (column: string) => {
    const direction = cacheSort.column === column && cacheSort.direction === 'asc' ? 'desc' : 'asc'
    setCacheSort({ column, direction })
  }

  // Handle page change
  const handlePageChange = (page: number) => {
    setCachePagination({ page })
  }

  // Handle page size change
  const handlePageSizeChange = (pageSize: number) => {
    setCachePagination({ pageSize, page: 1 })
  }

  return (
    <div className="space-y-6">
      {/* Page Header */}
      <div className="page-header">
        <div>
          <h1 className="page-title">Cache</h1>
          <p className="page-description">Monitor cache performance across L1 Exact, L2 Semantic, and L3 Context layers</p>
        </div>
        <div className="flex items-center gap-2">
          <Button variant="secondary" size="sm" onClick={() => window.location.reload()}>
            <RefreshCw className="w-4 h-4" />
            Refresh
          </Button>
        </div>
      </div>

      {/* Tabs */}
      <Tabs value={activeTab} onValueChange={setActiveTab}>
        <TabsList>
          <TabsTrigger value="overview">
            <Database className="w-4 h-4 mr-2" />
            Overview
          </TabsTrigger>
          <TabsTrigger value="entries">
            <BarChart3 className="w-4 h-4 mr-2" />
            Entries
          </TabsTrigger>
          <TabsTrigger value="analytics">
            <PieChart className="w-4 h-4 mr-2" />
            Analytics
          </TabsTrigger>
        </TabsList>

        {/* Overview Tab */}
        <TabsContent value="overview" className="mt-6">
          <div className="space-y-6">
            {/* Total Hit Rate */}
            <TotalCacheHitRate
              hitRate={totalHitRate}
              l1Rate={l1Rate}
              l2Rate={l2Rate}
              l3Rate={l3Rate}
            />

            {/* Layer Metrics */}
            {metrics && (
              <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4">
                {Object.entries(metrics.layers).map(([layerName, layerData]) => (
                  layerData ? (
                    <CacheLayerMetric
                      key={layerName}
                      layer={layerName}
                      hitRate={layerData.hitRate}
                      requests={layerData.requests}
                      tokensSaved={layerData.tokensSaved}
                      latencySaved={layerData.latencySaved}
                      entries={layerData.entries}
                    />
                  ) : null
                ))}
              </div>
            )}

            {/* Summary Stats */}
            {metrics && (
              <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4">
                <Card>
                  <CardContent className="pt-4">
                    <div className="flex items-center justify-between">
                      <div>
                        <p className="text-metadata text-text-muted">TOTAL ENTRIES</p>
                        <p className="text-2xl font-semibold font-mono tabular-nums">{formatNumber(metrics.totalEntries)}</p>
                      </div>
                      <Database className="w-8 h-8 text-text-muted/30" />
                    </div>
                  </CardContent>
                </Card>
                <Card>
                  <CardContent className="pt-4">
                    <div className="flex items-center justify-between">
                      <div>
                        <p className="text-metadata text-text-muted">MEMORY USAGE</p>
                        <p className="text-2xl font-semibold font-mono tabular-nums">{formatBytes(metrics.memoryUsage * 1024 * 1024 * 1024)}</p>
                      </div>
                      <Database className="w-8 h-8 text-text-muted/30" />
                    </div>
                  </CardContent>
                </Card>
                <Card>
                  <CardContent className="pt-4">
                    <div className="flex items-center justify-between">
                      <div>
                        <p className="text-metadata text-text-muted">EVICTIONS</p>
                        <p className="text-2xl font-semibold font-mono tabular-nums">{formatNumber(metrics.evictions)}</p>
                      </div>
                      <Database className="w-8 h-8 text-text-muted/30" />
                    </div>
                  </CardContent>
                </Card>
                <Card>
                  <CardContent className="pt-4">
                    <div className="flex items-center justify-between">
                      <div>
                        <p className="text-metadata text-text-muted">INVALIDATIONS</p>
                        <p className="text-2xl font-semibold font-mono tabular-nums">{formatNumber(metrics.invalidations)}</p>
                      </div>
                      <Database className="w-8 h-8 text-text-muted/30" />
                    </div>
                  </CardContent>
                </Card>
              </div>
            )}

            {/* Performance Chart */}
            <Card>
              <CardContent className="pt-4">
                <h3 className="text-section-title mb-4">LAYER PERFORMANCE COMPARISON</h3>
                <CachePerformanceChart
                  data={[
                    { layer: 'L1 Exact', hitRate: l1Rate, color: '#FF6B3D' },
                    { layer: 'L2 Semantic', hitRate: l2Rate, color: '#60A5FA' },
                    { layer: 'L3 Context', hitRate: l3Rate, color: '#F59E0B' },
                  ]}
                  height={200}
                />
              </CardContent>
            </Card>
          </div>
        </TabsContent>

        {/* Entries Tab */}
        <TabsContent value="entries" className="mt-6">
          {/* Filters */}
          <div className="flex items-center justify-between gap-4 mb-4">
            <div className="flex items-center gap-3 flex-1">
              <Input
                placeholder="Search cache keys..."
                value={cacheFilters.model || ''}
                onChange={(e) => setCacheFilters({ model: e.target.value || undefined })}
                leftIcon={<Search className="w-4 h-4" />}
                className="max-w-xs"
              />
              <Select
                value={cacheFilters.layer || ''}
                onChange={(e) => setCacheFilters({ layer: e.target.value || undefined })}
                options={LAYER_OPTIONS}
                className="w-40"
              />
              <Select
                value={cacheFilters.status || ''}
                onChange={(e) => setCacheFilters({ status: e.target.value || undefined })}
                options={STATUS_OPTIONS}
                className="w-40"
              />
            </div>
          </div>

          {/* Table */}
          <Card>
            <CardContent className="p-0">
              {loading ? (
                <div className="p-4 space-y-3">
                  {Array.from({ length: 5 }).map((_, i) => (
                    <LoadingSkeleton key={i} variant="table-row" />
                  ))}
                </div>
              ) : cacheEntries.length === 0 ? (
                <EmptyState
                  icon={<Database className="w-12 h-12" />}
                  title="No cache entries found"
                  description="Try adjusting your filters"
                />
              ) : (
                <div className="overflow-x-auto">
                  <table className="table">
                    <thead>
                      <tr>
                        <th className="cursor-pointer" onClick={() => handleSort('key')}>
                          KEY
                          {cacheSort.column === 'key' && (
                            <span className="ml-1">{cacheSort.direction === 'asc' ? <ChevronUp className="w-3 h-3" /> : <ChevronDown className="w-3 h-3" />}</span>
                          )}
                        </th>
                        <th className="cursor-pointer" onClick={() => handleSort('layer')}>
                          LAYER
                          {cacheSort.column === 'layer' && (
                            <span className="ml-1">{cacheSort.direction === 'asc' ? <ChevronUp className="w-3 h-3" /> : <ChevronDown className="w-3 h-3" />}</span>
                          )}
                        </th>
                        <th className="cursor-pointer" onClick={() => handleSort('model')}>
                          MODEL
                          {cacheSort.column === 'model' && (
                            <span className="ml-1">{cacheSort.direction === 'asc' ? <ChevronUp className="w-3 h-3" /> : <ChevronDown className="w-3 h-3" />}</span>
                          )}
                        </th>
                        <th className="cursor-pointer" onClick={() => handleSort('similarity')}>
                          SIMILARITY
                          {cacheSort.column === 'similarity' && (
                            <span className="ml-1">{cacheSort.direction === 'asc' ? <ChevronUp className="w-3 h-3" /> : <ChevronDown className="w-3 h-3" />}</span>
                          )}
                        </th>
                        <th className="cursor-pointer text-right" onClick={() => handleSort('tokensSaved')}>
                          TOKENS SAVED
                          {cacheSort.column === 'tokensSaved' && (
                            <span className="ml-1">{cacheSort.direction === 'asc' ? <ChevronUp className="w-3 h-3" /> : <ChevronDown className="w-3 h-3" />}</span>
                          )}
                        </th>
                        <th className="cursor-pointer" onClick={() => handleSort('createdAt')}>
                          CREATED
                          {cacheSort.column === 'createdAt' && (
                            <span className="ml-1">{cacheSort.direction === 'asc' ? <ChevronUp className="w-3 h-3" /> : <ChevronDown className="w-3 h-3" />}</span>
                          )}
                        </th>
                        <th className="cursor-pointer" onClick={() => handleSort('expiresAt')}>
                          EXPIRES
                          {cacheSort.column === 'expiresAt' && (
                            <span className="ml-1">{cacheSort.direction === 'asc' ? <ChevronUp className="w-3 h-3" /> : <ChevronDown className="w-3 h-3" />}</span>
                          )}
                        </th>
                        <th className="cursor-pointer" onClick={() => handleSort('status')}>
                          STATUS
                          {cacheSort.column === 'status' && (
                            <span className="ml-1">{cacheSort.direction === 'asc' ? <ChevronUp className="w-3 h-3" /> : <ChevronDown className="w-3 h-3" />}</span>
                          )}
                        </th>
                      </tr>
                    </thead>
                    <tbody>
                      {cacheEntries.map((entry) => (
                        <tr key={entry.key}>
                          <td className="font-mono text-code max-w-[200px] truncate">{entry.key}</td>
                          <td>
                            <Badge
                              variant={
                                entry.layer === 'L1' ? 'accent' :
                                entry.layer === 'L2' ? 'info' : 'warning'
                              }
                            >
                              {entry.layer}
                            </Badge>
                          </td>
                          <td className="font-mono text-code">{entry.model}</td>
                          <td className="font-mono tabular-nums">
                            {entry.similarity !== null ? formatPercent(entry.similarity) : '—'}
                          </td>
                          <td className="font-mono tabular-nums text-right text-success">{formatNumber(entry.tokensSaved)}</td>
                          <td className="text-metadata text-text-muted">{formatRelativeTime(entry.createdAt)}</td>
                          <td className="text-metadata text-text-muted">{formatRelativeTime(entry.expiresAt)}</td>
                          <td>
                            <Badge
                              variant={
                                entry.status === 'active' ? 'success' :
                                entry.status === 'expired' ? 'warning' : 'error'
                              }
                            >
                              {entry.status}
                            </Badge>
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              )}

              {/* Pagination */}
              <div className="flex items-center justify-between px-4 py-3 border-t border-border-subtle">
                <div className="flex items-center gap-2">
                  <Button
                    variant="ghost"
                    size="sm"
                    onClick={() => handlePageChange(cachePagination.page - 1)}
                    disabled={cachePagination.page <= 1}
                  >
                    <ChevronLeft className="w-4 h-4" />
                  </Button>
                  <span className="text-body text-text-secondary">
                    Page {cachePagination.page} of {Math.ceil(cachePagination.total / cachePagination.pageSize)}
                  </span>
                  <Button
                    variant="ghost"
                    size="sm"
                    onClick={() => handlePageChange(cachePagination.page + 1)}
                    disabled={cachePagination.page >= Math.ceil(cachePagination.total / cachePagination.pageSize)}
                  >
                    <ChevronRight className="w-4 h-4" />
                  </Button>
                </div>
                <div className="flex items-center gap-2">
                  <select
                    value={cachePagination.pageSize}
                    onChange={(e) => handlePageSizeChange(Number(e.target.value))}
                    className="select w-auto px-2 py-1 text-metadata"
                  >
                    {PAGE_SIZES.map(size => (
                      <option key={size} value={size}>{size} per page</option>
                    ))}
                  </select>
                  <span className="text-metadata text-text-muted">
                    {cachePagination.total.toLocaleString()} total
                  </span>
                </div>
              </div>
            </CardContent>
          </Card>
        </TabsContent>

        {/* Analytics Tab */}
        <TabsContent value="analytics" className="mt-6">
          <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
            {/* Top Models by Cache Performance */}
            <Card>
              <CardContent className="pt-4">
                <h3 className="text-section-title mb-4">MODEL CACHE PERFORMANCE</h3>
                <ModelComparisonChart
                  data={[
                    { name: 'claude-sonnet-4.6', requests: 128492, cacheHitRate: 0.782, cost: 24.50 },
                    { name: 'gpt-5', requests: 98234, cacheHitRate: 0.715, cost: 31.20 },
                    { name: 'gemini-2.5-pro', requests: 67891, cacheHitRate: 0.653, cost: 18.90 },
                    { name: 'llama-3.1-405b', requests: 45672, cacheHitRate: 0.821, cost: 12.40 },
                    { name: 'gpt-5-mini', requests: 43102, cacheHitRate: 0.698, cost: 8.75 },
                  ]}
                  metric="cacheHitRate"
                  height={300}
                />
              </CardContent>
            </Card>

            {/* Cache Efficiency */}
            <Card>
              <CardContent className="pt-4">
                <h3 className="text-section-title mb-4">CACHE EFFICIENCY</h3>
                <ModelComparisonChart
                  data={[
                    { name: 'L1 Exact', requests: 0, cacheHitRate: l1Rate * 100, cost: 0 },
                    { name: 'L2 Semantic', requests: 0, cacheHitRate: l2Rate * 100, cost: 0 },
                    { name: 'L3 Context', requests: 0, cacheHitRate: l3Rate * 100, cost: 0 },
                  ]}
                  metric="cacheHitRate"
                  height={300}
                />
              </CardContent>
            </Card>

            {/* Cache Stats Detail */}
            <Card className="lg:col-span-2">
              <CardContent className="pt-4">
                <h3 className="text-section-title mb-4">DETAILED STATISTICS</h3>
                <div className="grid grid-cols-2 lg:grid-cols-4 gap-6">
                  <div>
                    <h4 className="text-body font-medium text-text-secondary mb-3">L1 EXACT CACHE</h4>
                    <div className="space-y-2 text-metadata">
                      <div className="flex justify-between"><span>Hit Rate</span><span className="font-mono font-medium">{formatPercent(l1Rate)}</span></div>
                      <div className="flex justify-between"><span>Requests</span><span className="font-mono font-medium">{formatNumber(metrics?.layers.L1.requests || 0)}</span></div>
                      <div className="flex justify-between"><span>Tokens Saved</span><span className="font-mono font-medium text-success">{formatNumber(metrics?.layers.L1.tokensSaved || 0)}</span></div>
                      <div className="flex justify-between"><span>Avg Latency Saved</span><span className="font-mono font-medium">{formatDuration((metrics?.layers.L1.latencySaved || 0) * 1000000)}</span></div>
                      <div className="flex justify-between"><span>Entries</span><span className="font-mono font-medium">{formatNumber(metrics?.layers.L1.entries || 0)}</span></div>
                    </div>
                  </div>
                  <div>
                    <h4 className="text-body font-medium text-text-secondary mb-3">L2 SEMANTIC CACHE</h4>
                    <div className="space-y-2 text-metadata">
                      <div className="flex justify-between"><span>Hit Rate</span><span className="font-mono font-medium">{formatPercent(l2Rate)}</span></div>
                      <div className="flex justify-between"><span>Requests</span><span className="font-mono font-medium">{formatNumber(metrics?.layers.L2.requests || 0)}</span></div>
                      <div className="flex justify-between"><span>Tokens Saved</span><span className="font-mono font-medium text-success">{formatNumber(metrics?.layers.L2.tokensSaved || 0)}</span></div>
                      <div className="flex justify-between"><span>Avg Latency Saved</span><span className="font-mono font-medium">{formatDuration((metrics?.layers.L2.latencySaved || 0) * 1000000)}</span></div>
                      <div className="flex justify-between"><span>Entries</span><span className="font-mono font-medium">{formatNumber(metrics?.layers.L2.entries || 0)}</span></div>
                    </div>
                  </div>
                  <div>
                    <h4 className="text-body font-medium text-text-secondary mb-3">L3 CONTEXT CACHE</h4>
                    <div className="space-y-2 text-metadata">
                      <div className="flex justify-between"><span>Hit Rate</span><span className="font-mono font-medium">{formatPercent(l3Rate)}</span></div>
                      <div className="flex justify-between"><span>Requests</span><span className="font-mono font-medium">{formatNumber(metrics?.layers.L3.requests || 0)}</span></div>
                      <div className="flex justify-between"><span>Tokens Saved</span><span className="font-mono font-medium text-success">{formatNumber(metrics?.layers.L3.tokensSaved || 0)}</span></div>
                      <div className="flex justify-between"><span>Avg Latency Saved</span><span className="font-mono font-medium">{formatDuration((metrics?.layers.L3.latencySaved || 0) * 1000000)}</span></div>
                      <div className="flex justify-between"><span>Entries</span><span className="font-mono font-medium">{formatNumber(metrics?.layers.L3.entries || 0)}</span></div>
                    </div>
                  </div>
                  <div>
                    <h4 className="text-body font-medium text-text-secondary mb-3">AGGREGATE</h4>
                    <div className="space-y-2 text-metadata">
                      <div className="flex justify-between"><span>Total Hit Rate</span><span className="font-mono font-medium text-accent">{formatPercent(totalHitRate)}</span></div>
                      <div className="flex justify-between"><span>Avg Similarity</span><span className="font-mono font-medium">{formatPercent(metrics?.avgSimilarity || 0)}</span></div>
                      <div className="flex justify-between"><span>Avg Tokens Saved</span><span className="font-mono font-medium text-success">{formatNumber(metrics?.avgTokensSaved || 0)}/req</span></div>
                      <div className="flex justify-between"><span>Evictions</span><span className="font-mono font-medium">{formatNumber(metrics?.evictions || 0)}</span></div>
                      <div className="flex justify-between"><span>Invalidations</span><span className="font-mono font-medium">{formatNumber(metrics?.invalidations || 0)}</span></div>
                    </div>
                  </div>
                </div>
              </CardContent>
            </Card>
          </div>
        </TabsContent>
      </Tabs>
    </div>
  )
}