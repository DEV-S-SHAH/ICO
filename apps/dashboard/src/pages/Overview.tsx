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
import { formatNumber, formatPercent, formatDuration, formatRelativeTime } from '@/lib/formatters'
import { MetricCard, MetricRow, CacheLayerMetric, TotalCacheHitRate } from '@/components/metrics'
import { RequestVolumeChart, CachePerformanceChart } from '@/components/charts'
import { Button, Badge, Card, CardContent, Divider, Tabs, TabsList, TabsTrigger, TabsContent } from '@/components/common'
import { useUIStore, useDataStore } from '@/lib/stores'
import { getApiClient } from '@/lib/api/client'
import { generateMockTimeSeries, mockOverviewMetrics, mockCacheMetrics } from '@/data/mock'
import type { OverviewMetrics, TimeSeriesPoint, TimeRange } from '@/types'

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
  const { demoMode, liveTick } = useUIStore()
  const { overviewMetrics, setOverviewMetrics, timeSeriesData, setTimeSeriesData } = useDataStore()
  const [timeRange, setTimeRange] = useState<TimeRange>('24h')
  const [selectedMetric, setSelectedMetric] = useState<'requests' | 'tokens' | 'cost' | 'latency'>('requests')
  const [loading, setLoading] = useState(true)
  const [chartData, setChartData] = useState<TimeSeriesPoint[]>([])
  const [cacheMetrics, setCacheMetrics] = useState<typeof mockCacheMetrics | null>(demoMode ? mockCacheMetrics : null)

  // Load data (silent=true for background live refreshes to avoid flicker)
  const loadData = useCallback(async (silent = false) => {
    if (!silent) setLoading(true)
    const api = getApiClient(demoMode)
    try {
      const [overview, series, metrics] = await Promise.all([
        api.getOverviewMetrics(),
        api.getTimeSeries(selectedMetric, timeRange),
        api.getCacheMetrics(),
      ])
      setOverviewMetrics(overview)
      setTimeSeriesData(`${selectedMetric}-${timeRange}`, series)
      setChartData(series)
      setCacheMetrics(metrics)
    } catch (error) {
      console.error('Failed to load overview data:', error)
      if (demoMode) {
        setOverviewMetrics(mockOverviewMetrics)
        const series = generateMockTimeSeries(selectedMetric, timeRange)
        setTimeSeriesData(`${selectedMetric}-${timeRange}`, series)
        setChartData(series)
        setCacheMetrics(mockCacheMetrics)
      }
      // Live mode: keep last real values; never substitute dummy data
    } finally {
      setLoading(false)
    }
  }, [demoMode, selectedMetric, timeRange, setOverviewMetrics, setTimeSeriesData])

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
              {[
                { type: 'cache-hit', label: 'L2 Cache Hit', detail: 'claude-sonnet-4.6 • 0.94 similarity • 3,605 tokens saved', time: '2m ago', color: 'text-success' },
                { type: 'cache-miss', label: 'Cache Miss → LLM', detail: 'gpt-5 • /v1/chat/completions • 1,247ms', time: '5m ago', color: 'text-warning' },
                { type: 'cache-hit', label: 'L1 Cache Hit', detail: 'gemini-2.5-pro • Exact match • 892 tokens saved', time: '8m ago', color: 'text-success' },
                { type: 'invalidation', label: 'Cache Invalidation', detail: 'Tenant: tenant_a • 1,234 entries purged', time: '12m ago', color: 'text-info' },
                { type: 'error', label: 'Provider Error', detail: 'Anthropic • Rate limited • Retrying...', time: '15m ago', color: 'text-error' },
              ].map((activity, index) => (
                <div key={index} className="flex items-start gap-3 p-3 rounded-lg hover:bg-bg-elevated/50 transition-colors">
                  <div className={cn('w-2 h-2 rounded-full mt-2 flex-shrink-0', activity.color.replace('text-', 'bg-'))} />
                  <div className="flex-1 min-w-0">
                    <p className="text-body font-medium text-text-primary">{activity.label}</p>
                    <p className="text-metadata text-text-muted mt-0.5 truncate">{activity.detail}</p>
                  </div>
                  <span className="text-metadata text-text-muted flex-shrink-0">{activity.time}</span>
                </div>
              ))}
            </div>
          </CardContent>
        </Card>

        {/* System Health */}
        <Card>
          <CardContent className="pt-4">
            <h3 className="text-section-title mb-4">SYSTEM HEALTH</h3>
            <div className="space-y-4">
              {[
                { name: 'API Gateway', status: 'healthy', latency: '12ms', uptime: '99.99%' },
                { name: 'Redis (L1 Cache)', status: 'healthy', latency: '2ms', uptime: '99.99%' },
                { name: 'Qdrant (L2/L3)', status: 'healthy', latency: '18ms', uptime: '99.95%' },
                { name: 'Anthropic', status: 'healthy', latency: '245ms', uptime: '99.90%' },
                { name: 'OpenAI', status: 'degraded', latency: '890ms', uptime: '99.50%' },
                { name: 'Google AI', status: 'healthy', latency: '156ms', uptime: '99.95%' },
              ].map((service, index) => (
                <div key={index} className="flex items-center justify-between p-3 rounded-lg hover:bg-bg-elevated/50 transition-colors">
                  <div className="flex items-center gap-3">
                    <div className={cn('w-2.5 h-2.5 rounded-full', service.status === 'healthy' ? 'bg-success' : 'bg-warning')} />
                    <span className="text-body font-medium">{service.name}</span>
                  </div>
                  <div className="flex items-center gap-4 text-metadata text-text-muted">
                    <span className="font-mono">{service.latency}</span>
                    <span className="font-mono">{service.uptime}</span>
                    <Badge variant={service.status === 'healthy' ? 'success' : 'warning'}>{service.status}</Badge>
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
                  <th>TREND</th>
                </tr>
              </thead>
              <tbody>
                {[
                  { model: 'claude-sonnet-4.6', provider: 'Anthropic', requests: '128,492', hitRate: '78.2%', latency: '312ms', cost: '$24.50', trend: '+12.4%' },
                  { model: 'gpt-5', provider: 'OpenAI', requests: '98,234', hitRate: '71.5%', latency: '425ms', cost: '$31.20', trend: '+8.1%' },
                  { model: 'gemini-2.5-pro', provider: 'Google', requests: '67,891', hitRate: '65.3%', latency: '287ms', cost: '$18.90', trend: '-2.3%' },
                  { model: 'llama-3.1-405b', provider: 'Meta', requests: '45,672', hitRate: '82.1%', latency: '512ms', cost: '$12.40', trend: '+22.8%' },
                  { model: 'gpt-5-mini', provider: 'OpenAI', requests: '43,102', hitRate: '69.8%', latency: '198ms', cost: '$8.75', trend: '+15.2%' },
                ].map((row, index) => (
                  <tr key={index}>
                    <td><code className="code">{row.model}</code></td>
                    <td className="text-text-secondary">{row.provider}</td>
                    <td className="font-mono tabular-nums">{row.requests}</td>
                    <td><Badge variant={parseFloat(row.hitRate) > 70 ? 'success' : 'warning'}>{row.hitRate}</Badge></td>
                    <td className="font-mono tabular-nums">{row.latency}</td>
                    <td className="font-mono tabular-nums">{row.cost}</td>
                    <td className={cn('font-mono font-medium', row.trend.startsWith('-') ? 'text-error' : 'text-success')}>{row.trend}</td>
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