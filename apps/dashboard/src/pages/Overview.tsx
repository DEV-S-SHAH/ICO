// Overview Dashboard Page

import { useEffect, useState, useCallback } from 'react'
import { useNavigate } from 'react-router-dom'
import {
  Clock,
  Zap,
  Database,
  DollarSign,
  TrendingUp,
  TrendingDown,
  Activity,
  RefreshCw,
  ChevronLeft,
  ChevronRight,
} from 'lucide-react'
import { cn } from '@/components/common'
import { formatNumber, formatPercent, formatDuration, formatRelativeTime, formatCurrency } from '@/lib/formatters'
import { MetricCard, MetricRow, CacheLayerMetric, TotalCacheHitRate } from '@/components/metrics'
import { RequestVolumeChart, CachePerformanceChart } from '@/components/charts'
import { Button, Badge, Card, CardContent, Divider, Tabs, TabsList, TabsTrigger, TabsContent } from '@/components/common'
import { useUIStore, useDataStore } from '@/lib/stores'
import { getApiClient } from '@/lib/api/client'
import type { OverviewMetrics, CacheMetrics, TimeSeriesPoint, TimeRange } from '@/types'

const TIME_RANGES: Array<{ value: TimeRange; label: string }> = [
  { value: '1h', label: '1H' },
  { value: '24h', label: '24H' },
  { value: '7d', label: '7D' },
  { value: '30d', label: '30D' },
]

const METRICS: Array<{ value: 'requests' | 'tokens' | 'cost' | 'latency'; label: string }> = [
  { value: 'requests', label: 'Requests' },
  { value: 'tokens', label: 'Tokens' },
  { value: 'cost', label: 'Cost' },
  { value: 'latency', label: 'Latency' },
]

export function Overview() {
  const navigate = useNavigate()
  const { connected, liveTick } = useUIStore()
  const { overviewMetrics, setOverviewMetrics, timeSeriesData, setTimeSeriesData, models, providers, requests, setRequests } = useDataStore()
  const [timeRange, setTimeRange] = useState<TimeRange>('24h')
  const [selectedMetric, setSelectedMetric] = useState<'requests' | 'tokens' | 'cost' | 'latency'>('requests')
  const [loading, setLoading] = useState(true)
  const [chartData, setChartData] = useState<TimeSeriesPoint[]>([])
  const [cacheMetrics, setCacheMetrics] = useState<CacheMetrics | null>(null)

  // Load data (silent=true for background live refreshes to avoid flicker)
  const loadData = useCallback(async (silent = false) => {
    if (!silent) setLoading(true)
    const api = getApiClient()
    try {
      const [overview, series, metrics, recent] = await Promise.all([
        api.getOverviewMetrics(),
        api.getTimeSeries(selectedMetric, timeRange),
        api.getCacheMetrics(),
        api.getRequests(
          { status: 'all', model: 'all', provider: 'all', cache: 'all', endpoint: 'all', timeRange: '24h', search: '' },
          { page: 1, pageSize: 8, total: 0 },
          { column: 'timestamp', direction: 'desc' }
        ),
      ])
      setOverviewMetrics(overview)
      setTimeSeriesData(`${selectedMetric}-${timeRange}`, series)
      setChartData(series)
      setCacheMetrics(metrics)
      setRequests(recent.data)
    } catch (error) {
      console.error('Failed to load overview data:', error)
    } finally {
      setLoading(false)
    }
  }, [selectedMetric, timeRange, setOverviewMetrics, setTimeSeriesData, setRequests])

  useEffect(() => {
    loadData()
  }, [loadData])

  // Re-fetch whenever the backend pushes a real event
  useEffect(() => {
    if (liveTick > 0) loadData(true)
  }, [liveTick]) // eslint-disable-line react-hooks/exhaustive-deps

  // Metrics for the top row
  const topMetrics = overviewMetrics ? [
    {
      label: 'REQUESTS',
      value: overviewMetrics.requests.value,
      trend: overviewMetrics.requests.trend,
      trendLabel: overviewMetrics.requests.trendLabel,
    },
    {
      label: 'CACHE HIT RATE',
      value: overviewMetrics.cacheHitRate.value,
      trend: overviewMetrics.cacheHitRate.trend,
      trendLabel: overviewMetrics.cacheHitRate.trendLabel,
    },
    {
      label: 'TOKENS SAVED',
      value: overviewMetrics.tokensSaved.value,
      trend: overviewMetrics.tokensSaved.trend,
      trendLabel: overviewMetrics.tokensSaved.trendLabel,
    },
    {
      label: 'EST. COST',
      value: overviewMetrics.estimatedCost.value,
      trend: overviewMetrics.estimatedCost.trend,
      trendLabel: overviewMetrics.estimatedCost.trendLabel,
    },
    {
      label: 'AVG LATENCY',
      value: overviewMetrics.avgLatency.value,
      trend: overviewMetrics.avgLatency.trend,
      trendLabel: overviewMetrics.avgLatency.trendLabel,
    },
  ] : []

  // Cache layer metrics
  const cacheLayers = cacheMetrics ? [
    { layer: 'L1' as const, ...cacheMetrics.layers.L1 },
    { layer: 'L2' as const, ...cacheMetrics.layers.L2 },
    { layer: 'L3' as const, ...cacheMetrics.layers.L3 },
  ] : []

  const totalHitRate = cacheMetrics?.hitRate || 0
  const l1Rate = cacheMetrics?.layers.L1.hitRate || 0
  const l2Rate = cacheMetrics?.layers.L2.hitRate || 0
  const l3Rate = cacheMetrics?.layers.L3.hitRate || 0

  return (
    <div className="space-y-6">
      {/* Page Header */}
      <div className="page-header">
        <div>
          <h1 className="page-title">Overview</h1>
          <p className="page-description">System-wide cache performance and request metrics</p>
        </div>
        <div className="flex items-center gap-2">
          <Button variant="ghost" size="sm" onClick={() => loadData()}>
            <RefreshCw className={cn("w-4 h-4", loading && "animate-spin")} />
            Refresh
          </Button>
        </div>
      </div>

      {/* Top Metrics Row */}
      <MetricRow metrics={topMetrics} />

      {/* Main Charts */}
      <div className="grid grid-cols-1 lg:grid-cols-3 gap-4">
        {/* Request Volume Chart - 2/3 width */}
        <div className="lg:col-span-2">
          <div className="panel p-4">
            <div className="flex items-center justify-between mb-4">
              <h2 className="text-section-title">REQUEST VOLUME</h2>
              <div className="flex items-center gap-2">
                {/* Time Range Selector */}
                <div className="flex items-center gap-1 bg-bg-elevated rounded-md p-1">
                  {TIME_RANGES.map(({ value, label }) => (
                    <button
                      key={value}
                      onClick={() => setTimeRange(value)}
                      className={cn(
                        'px-2.5 py-1 text-metadata font-medium rounded transition-colors duration-fast',
                        timeRange === value
                          ? 'bg-accent text-white'
                          : 'text-text-secondary hover:text-text-primary'
                      )}
                    >
                      {label}
                    </button>
                  ))}
                </div>
                {/* Metric Selector */}
                <select
                  value={selectedMetric}
                  onChange={(e) => setSelectedMetric(e.target.value as typeof selectedMetric)}
                  className="select w-auto px-2 py-1 text-metadata"
                >
                  {METRICS.map(m => (
                    <option key={m.value} value={m.value}>{m.label}</option>
                  ))}
                </select>
              </div>
            </div>
            {loading ? (
              <div className="h-64 flex items-center justify-center">
                <div className="animate-spin rounded-full h-8 w-8 border-b-2 border-accent" />
              </div>
            ) : (
              <RequestVolumeChart data={chartData} metric={selectedMetric} height={280} />
            )}
          </div>
        </div>

        {/* Cache Performance - 1/3 width */}
        <div className="space-y-4">
          <TotalCacheHitRate
            hitRate={totalHitRate}
            l1Rate={l1Rate}
            l2Rate={l2Rate}
            l3Rate={l3Rate}
          />
          <CachePerformanceChart
            data={[
              { layer: 'L1 Exact', hitRate: l1Rate, color: '#FF6B3D' },
              { layer: 'L2 Semantic', hitRate: l2Rate, color: '#60A5FA' },
              { layer: 'L3 Context', hitRate: l3Rate, color: '#F59E0B' },
            ]}
            height={200}
          />
        </div>
      </div>

      {/* Cache Layer Details */}
      <div className="grid grid-cols-1 lg:grid-cols-3 gap-4">
        {cacheLayers.map(layer => (
          <CacheLayerMetric key={layer.layer} {...layer} />
        ))}
      </div>

      {/* Recent Activity & Quick Stats */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
        {/* Recent Activity */}
        <Card>
          <CardContent className="pt-4">
            <div className="flex items-center justify-between mb-4">
              <h3 className="text-section-title">RECENT ACTIVITY</h3>
              <Button variant="ghost" size="sm" onClick={() => navigate('/requests')}>
                View All
                <ChevronRight className="w-3 h-3" />
              </Button>
            </div>
            <div className="space-y-3">
              {requests.slice(0, 6).map((request) => {
                const hit = request.cache?.status === 'HIT'
                const layer = request.cache?.layer || 'Cache'
                return (
                  <div key={request.id} className="flex items-start gap-3 p-3 rounded-lg hover:bg-bg-elevated/50 transition-colors">
                    <div className={cn('w-2 h-2 rounded-full mt-2 flex-shrink-0', hit ? 'bg-success' : 'bg-warning')} />
                    <div className="flex-1 min-w-0">
                      <p className="text-body font-medium text-text-primary">
                        {request.cache?.status ? `${layer} ${request.cache.status}` : 'Request'}
                      </p>
                      <p className="text-metadata text-text-muted mt-0.5 truncate">
                        {request.model} • {request.endpoint || '/v1/query'} • {request.latency}ms
                      </p>
                    </div>
                    <span className="text-metadata text-text-muted flex-shrink-0">{formatRelativeTime(request.timestamp)}</span>
                  </div>
                )
              })}
            </div>
          </CardContent>
        </Card>

        {/* System Health */}
        <Card>
          <CardContent className="pt-4">
            <h3 className="text-section-title mb-4">SYSTEM HEALTH</h3>
            <div className="space-y-4">
              <div className="flex items-center justify-between p-3 rounded-lg hover:bg-bg-elevated/50 transition-colors">
                <div className="flex items-center gap-3">
                  <div className={cn('w-2.5 h-2.5 rounded-full', connected ? 'bg-success' : 'bg-error')} />
                  <span className="text-body font-medium">API Server</span>
                </div>
                <div className="flex items-center gap-4 text-metadata text-text-muted">
                  <span className="font-mono">{connected ? 'healthy' : 'down'}</span>
                  <Badge variant={connected ? 'success' : 'error'}>{connected ? 'healthy' : 'down'}</Badge>
                </div>
              </div>
              {['L1', 'L2', 'L3'].map((layer) => {
                const layerMetrics = cacheMetrics?.layers[layer]
                if (!layerMetrics) return null
                return (
                  <div key={layer} className="flex items-center justify-between p-3 rounded-lg hover:bg-bg-elevated/50 transition-colors">
                    <div className="flex items-center gap-3">
                      <div className={cn('w-2.5 h-2.5 rounded-full', layerMetrics.requests > 0 ? 'bg-success' : 'bg-warning')} />
                      <span className="text-body font-medium">{layer} Cache</span>
                    </div>
                    <div className="flex items-center gap-4 text-metadata text-text-muted">
                      <span className="font-mono">{formatPercent(layerMetrics.hitRate)} hit</span>
                      <span className="font-mono">{formatNumber(layerMetrics.entries)} entries</span>
                      <Badge variant={layerMetrics.requests > 0 ? 'success' : 'warning'}>{layerMetrics.requests > 0 ? 'healthy' : 'idle'}</Badge>
                    </div>
                  </div>
                )
              })}
              {providers.map((provider) => (
                <div key={provider.id} className="flex items-center justify-between p-3 rounded-lg hover:bg-bg-elevated/50 transition-colors">
                  <div className="flex items-center gap-3">
                    <div className={cn('w-2.5 h-2.5 rounded-full', provider.status === 'healthy' ? 'bg-success' : provider.status === 'degraded' ? 'bg-warning' : 'bg-error')} />
                    <span className="text-body font-medium">{provider.name}</span>
                  </div>
                  <div className="flex items-center gap-4 text-metadata text-text-muted">
                    <span className="font-mono">{formatDuration(provider.avgLatency)}</span>
                    <span className="font-mono">{formatNumber(provider.requests)} reqs</span>
                    <Badge variant={provider.status === 'healthy' ? 'success' : 'warning'}>{provider.status}</Badge>
                  </div>
                </div>
              ))}
            </div>
          </CardContent>
        </Card>
      </div>

      {/* Top Models by Usage */}
      <Card>
        <CardContent className="pt-4">
          <div className="flex items-center justify-between mb-4">
            <h3 className="text-section-title">TOP MODELS BY USAGE</h3>
            <Button variant="ghost" size="sm" onClick={() => navigate('/models')}>
              View All
              <ChevronRight className="w-3 h-3" />
            </Button>
          </div>
          <div className="overflow-x-auto">
            <table className="table">
              <thead>
                <tr>
                  <th>MODEL</th>
                  <th>PROVIDER</th>
                  <th>REQUESTS</th>
                  <th>CACHE HIT RATE</th>
                  <th>AVG LATENCY</th>
                  <th>COST</th>
                </tr>
              </thead>
              <tbody>
                {models.map((row) => (
                  <tr key={row.id}>
                    <td><code className="code">{row.name}</code></td>
                    <td className="text-text-secondary">{row.provider}</td>
                    <td className="font-mono tabular-nums">{formatNumber(row.requests)}</td>
                    <td><Badge variant={row.cacheHitRate > 0.5 ? 'success' : 'warning'}>{formatPercent(row.cacheHitRate)}</Badge></td>
                    <td className="font-mono tabular-nums">{formatDuration(row.avgLatency)}</td>
                    <td className="font-mono tabular-nums">{formatCurrency(row.cost)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </CardContent>
      </Card>
    </div>
  )
}