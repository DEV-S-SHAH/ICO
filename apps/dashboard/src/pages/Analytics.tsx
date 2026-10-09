// Analytics Page

import { useEffect, useState } from 'react'
import {
  BarChart3,
  LineChart,
  PieChart,
  Download,
  RefreshCw,
} from 'lucide-react'
import { formatNumber, formatDuration, formatPercent, formatCurrency } from '@/lib/formatters'
import {
  Button,
  Select,
  Card,
  CardContent,
  Badge,
  Progress,
  Divider,
} from '@/components/common'
import {
  RequestVolumeChart,
  CostChart,
  CachePerformanceChart,
  ModelComparisonChart,
  Sparkline,
} from '@/components/charts'
import { useUIStore, useDataStore } from '@/lib/stores'
import { apiClient } from '@/lib/api/client'
import type { TimeSeriesPoint, Request } from '@/types'


const TIME_RANGES = [
  { value: '1h', label: 'Last Hour' },
  { value: '6h', label: 'Last 6 Hours' },
  { value: '24h', label: 'Last 24 Hours' },
  { value: '7d', label: 'Last 7 Days' },
  { value: '30d', label: 'Last 30 Days' },
  { value: '90d', label: 'Last 90 Days' },
]

const LAYER_COLORS: Record<string, string> = {
  L0: '#FF6B3D',
  L0b: '#FF9E3D',
  L1: '#FF6B3D',
  L2: '#60A5FA',
  L3: '#F59E0B',
}

// Real cache hit-rate trend bucketed from actual request logs
function bucketHitRate(requests: Request[]): TimeSeriesPoint[] {
  const buckets = new Map<string, { hits: number; total: number }>()
  for (const r of requests) {
    if (!r.timestamp) continue
    const key = new Date(r.timestamp).toISOString().slice(0, 13)
    const bucket = buckets.get(key) || { hits: 0, total: 0 }
    bucket.total += 1
    if (r.cache?.status === 'HIT') bucket.hits += 1
    buckets.set(key, bucket)
  }
  return [...buckets.entries()]
    .sort(([a], [b]) => a.localeCompare(b))
    .map(([timestamp, b]) => ({ timestamp, value: b.total ? b.hits / b.total : 0 }))
}

export function Analytics() {
  const { liveTick } = useUIStore()
  const { overviewMetrics, models, providers, cacheMetrics, requests } = useDataStore()
  const [timeRange, setTimeRange] = useState('24h')
  const [activeTab, setActiveTab] = useState('overview')
  const [trends, setTrends] = useState<{ requests: TimeSeriesPoint[]; latency: TimeSeriesPoint[]; cost: TimeSeriesPoint[] }>({
    requests: [],
    latency: [],
    cost: [],
  })

  // Load real time series whenever the range changes or the backend pushes events
  useEffect(() => {
    let cancelled = false
    async function load() {
      try {
        const [requestsSeries, latencySeries, costSeries] = await Promise.all([
          apiClient.getTimeSeries('requests', timeRange as any),
          apiClient.getTimeSeries('latency', timeRange as any),
          apiClient.getTimeSeries('cost', timeRange as any),
        ])
        if (!cancelled) setTrends({ requests: requestsSeries, latency: latencySeries, cost: costSeries })
      } catch {
        // keep last values
      }
    }
    load()
    return () => { cancelled = true }
  }, [timeRange, liveTick])

  const totalRequestsLive = requests.length || Number(overviewMetrics?.requests.value ?? 0) || 0
  const avgLatencyLive = requests.length ? requests.reduce((s, r) => s + r.latency, 0) / requests.length : 0
  const cacheHitRateLive = cacheMetrics?.hitRate ?? (requests.length ? requests.filter(r => r.cache.status === 'HIT').length / requests.length : 0)
  const totalCostLive = requests.reduce((s, r) => s + r.cost.total, 0)

  const overview = {
    totalRequests: totalRequestsLive,
    avgLatency: avgLatencyLive,
    cacheHitRate: cacheHitRateLive,
    totalCost: totalCostLive,
    tokensUsed: models.reduce((sum, m) => sum + m.inputTokens + m.outputTokens, 0),
    errorRate: providers.length ? providers.reduce((sum, p) => sum + p.errorRate, 0) / providers.length : 0,
    activeModels: models.length,
  }

  const byModel = models.map((m) => ({
    name: m.name,
    requests: m.requests,
    cost: m.cost,
    cacheHitRate: m.cacheHitRate,
    tokens: m.inputTokens + m.outputTokens,
    latency: m.avgLatency,
    hitRate: m.cacheHitRate,
  }))

  const byProvider = providers.map((p) => ({
    provider: p.name,
    requests: p.requests,
    cost: p.cost,
    latency: p.avgLatency,
    hitRate: cacheMetrics?.hitRate ?? 0,
  }))

  const byCacheLayer = Object.entries(cacheMetrics?.layers ?? {}).map(([layer, l]) => {
    const requestsCount = l?.requests ?? 0
    const hits = Math.round(requestsCount * (l?.hitRate ?? 0))
    return {
      layer,
      hits,
      misses: requestsCount - hits,
      hitRate: l?.hitRate ?? 0,
      latency: l?.latencySaved ?? 0,
      color: LAYER_COLORS[layer] || '#60A5FA',
    }
  })

  const hitRateTrend = bucketHitRate(requests)
  const totalTokensUsed = overview.tokensUsed
  const promptTokens = models.reduce((sum, m) => sum + m.inputTokens, 0)
  const completionTokens = models.reduce((sum, m) => sum + m.outputTokens, 0)
  const tokensSavedByCache = models.reduce((sum, m) => sum + m.cachedTokens, 0)
  const totalProviderErrors = providers.reduce((sum, p) => sum + p.errors, 0)

  return (
    <div className="space-y-6">
      {/* Page Header */}
      <div className="page-header">
        <div>
          <h1 className="page-title flex items-center gap-2">
            <BarChart3 className="w-6 h-6" />
            Analytics
          </h1>
          <p className="page-description">Deep insights into cache performance, costs, and usage patterns</p>
        </div>
        <div className="flex items-center gap-2">
          <Select
            value={timeRange}
            onChange={(e) => setTimeRange(e.target.value)}
            options={TIME_RANGES}
            className="w-auto"
          />
          <Button variant="secondary" size="sm" onClick={() => {}}>
            <Download className="w-4 h-4 mr-1" />
            Export Report
          </Button>
          <Button variant="secondary" size="sm" onClick={() => window.location.reload()}>
            <RefreshCw className="w-4 h-4" />
          </Button>
        </div>
      </div>

      {/* Tabs */}
      <div className="border-b border-border-subtle">
        <nav className="flex gap-1 px-1" aria-label="Analytics tabs">
          {['overview', 'models', 'providers', 'cache', 'trends'].map(tab => (
            <button
              key={tab}
              onClick={() => setActiveTab(tab)}
              className={`px-4 py-2 text-body font-medium rounded-lg transition-colors ${
                activeTab === tab
                  ? 'bg-accent/10 text-accent border-b-2 border-accent'
                  : 'text-text-muted hover:text-text-primary hover:bg-bg-elevated/50'
              }`}
            >
              {tab.charAt(0).toUpperCase() + tab.slice(1)}
            </button>
          ))}
        </nav>
      </div>

      {/* Overview Tab */}
      {activeTab === 'overview' && (
        <>
          {/* Key Metrics */}
          <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4 mb-6">
            <Card>
              <CardContent className="pt-4">
                <div className="flex items-center justify-between">
                  <div>
                    <p className="text-metadata text-text-muted">TOTAL REQUESTS</p>
                    <p className="text-2xl font-semibold font-mono tabular-nums">{formatNumber(overview.totalRequests)}</p>
                  </div>
                  <div className="w-12 h-12 rounded-lg bg-blue-500/10 flex items-center justify-center">
                    <LineChart className="w-6 h-6 text-blue-500" />
                  </div>
                </div>
                <Sparkline data={trends.requests} className="mt-3 h-12" color="#3B82F6" />
              </CardContent>
            </Card>
            <Card>
              <CardContent className="pt-4">
                <div className="flex items-center justify-between">
                  <div>
                    <p className="text-metadata text-text-muted">AVG LATENCY</p>
                    <p className="text-2xl font-semibold font-mono tabular-nums">{formatDuration(overview.avgLatency)}</p>
                  </div>
                  <div className="w-12 h-12 rounded-lg bg-green-500/10 flex items-center justify-center">
                    <BarChart3 className="w-6 h-6 text-green-500" />
                  </div>
                </div>
                <Sparkline data={trends.latency} className="mt-3 h-12" color="#22C55E" />
              </CardContent>
            </Card>
            <Card>
              <CardContent className="pt-4">
                <div className="flex items-center justify-between">
                  <div>
                    <p className="text-metadata text-text-muted">CACHE HIT RATE</p>
                    <p className="text-2xl font-semibold font-mono tabular-nums">{formatPercent(overview.cacheHitRate)}</p>
                  </div>
                  <div className="w-12 h-12 rounded-lg bg-purple-500/10 flex items-center justify-center">
                    <PieChart className="w-6 h-6 text-purple-500" />
                  </div>
                </div>
                <Sparkline data={hitRateTrend} className="mt-3 h-12" color="#A855F7" />
              </CardContent>
            </Card>
            <Card>
              <CardContent className="pt-4">
                <div className="flex items-center justify-between">
                  <div>
                    <p className="text-metadata text-text-muted">TOTAL COST</p>
                    <p className="text-2xl font-semibold font-mono tabular-nums">{formatCurrency(overview.totalCost)}</p>
                  </div>
                  <div className="w-12 h-12 rounded-lg bg-orange-500/10 flex items-center justify-center">
                    <BarChart3 className="w-6 h-6 text-orange-500" />
                  </div>
                </div>
                <Sparkline data={trends.cost} className="mt-3 h-12" color="#F97316" />
              </CardContent>
            </Card>
          </div>

          {/* Charts Row 1 */}
          <div className="grid grid-cols-1 lg:grid-cols-2 gap-6 mb-6">
            <Card>
              <CardContent className="pt-4">
                <div className="flex items-center justify-between mb-4">
                  <h3 className="font-medium">Request Volume</h3>
                  <Badge variant="outline">{formatNumber(overview.totalRequests)} total</Badge>
                </div>
                <RequestVolumeChart 
                  data={trends.requests}
                  metric="requests"
                  height={300}
                />
              </CardContent>
            </Card>
            <Card>
              <CardContent className="pt-4">
                <div className="flex items-center justify-between mb-4">
                  <h3 className="font-medium">Cost Trend</h3>
                  <Badge variant="outline">{formatCurrency(overview.totalCost)} total</Badge>
                </div>
                <CostChart 
                  data={trends.cost.map(point => ({ name: new Date(point.timestamp).toLocaleTimeString(), input: point.value, output: 0, cached: 0 }))}
                  height={300}
                />
              </CardContent>
            </Card>
          </div>

          {/* Charts Row 2 */}
          <div className="grid grid-cols-1 lg:grid-cols-2 gap-6 mb-6">
            <Card>
              <CardContent className="pt-4">
                <div className="flex items-center justify-between mb-4">
                  <h3 className="font-medium">Cache Performance by Layer</h3>
                  <Badge variant="outline">{formatPercent(overview.cacheHitRate)} overall</Badge>
                </div>
                <CachePerformanceChart 
                  data={byCacheLayer.map(l => ({ layer: l.layer, hitRate: l.hitRate, color: l.color }))}
                  height={300}
                />
              </CardContent>
            </Card>
            <Card>
              <CardContent className="pt-4">
                <div className="flex items-center justify-between mb-4">
                  <h3 className="font-medium">Model Comparison</h3>
                  <Badge variant="outline">{overview.activeModels} active</Badge>
                </div>
                <ModelComparisonChart 
                  data={byModel.map(m => ({ name: m.name, requests: m.requests, cacheHitRate: m.cacheHitRate, cost: m.cost }))}
                  metric="cacheHitRate"
                  height={300}
                />
              </CardContent>
            </Card>
          </div>

          {/* Additional Metrics */}
          <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
            <Card>
              <CardContent className="pt-4">
                <h3 className="font-medium mb-4">Token Usage</h3>
                <div className="space-y-4">
                  <div>
                    <div className="flex items-center justify-between mb-2">
                      <span className="text-body">Total Tokens (used)</span>
                      <span className="font-mono tabular-nums">{formatNumber(totalTokensUsed)}</span>
                    </div>
                    <div className="grid grid-cols-2 gap-4">
                      <div>
                        <p className="text-metadata text-text-muted">Prompt Tokens</p>
                        <p className="font-mono tabular-nums">{formatNumber(promptTokens)}</p>
                      </div>
                      <div>
                        <p className="text-metadata text-text-muted">Completion Tokens</p>
                        <p className="font-mono tabular-nums">{formatNumber(completionTokens)}</p>
                      </div>
                    </div>
                  </div>
                  <div className="flex items-center justify-between">
                    <span className="text-body">Tokens Saved (cache)</span>
                    <span className="font-mono tabular-nums text-success">{formatNumber(tokensSavedByCache)}</span>
                  </div>
                </div>
              </CardContent>
            </Card>
            <Card>
              <CardContent className="pt-4">
                <h3 className="font-medium mb-4">Error Analysis</h3>
                <div className="space-y-3">
                  <div className="flex items-center justify-between">
                    <span className="text-body">Error Rate</span>
                    <Badge variant={overview.errorRate > 0.01 ? 'error' : 'success'}>{formatPercent(overview.errorRate)}</Badge>
                  </div>
                  <Progress value={Math.min(overview.errorRate * 100, 100)} max={100} className="h-2" />
                  <div className="pt-2 space-y-2">
                    {providers.length === 0 && (
                      <p className="text-metadata text-text-muted">No provider activity recorded yet</p>
                    )}
                    {providers.map(p => (
                      <div key={p.id} className="flex items-center justify-between">
                        <span className="text-body text-text-muted">{p.name}</span>
                        <span className="font-mono tabular-nums text-error">{formatNumber(p.errors)} errors</span>
                      </div>
                    ))}
                  </div>
                </div>
              </CardContent>
            </Card>
          </div>
        </>
      )}

      {/* Models Tab */}
      {activeTab === 'models' && (
        <div className="space-y-6">
          <Card>
            <CardContent className="pt-4">
              <h3 className="font-medium mb-4">Model Performance Comparison</h3>
              <ModelComparisonChart 
                data={byModel.map(m => ({ name: m.name, requests: m.requests, cacheHitRate: m.cacheHitRate, cost: m.cost }))}
                metric="cost"
                height={400}
              />
            </CardContent>
          </Card>
          <Card>
            <CardContent className="pt-4">
              <h3 className="font-medium mb-4">Model Details</h3>
              <div className="overflow-x-auto">
                <table className="table">
                  <thead>
                    <tr>
                      <th>MODEL</th>
                      <th className="text-right">REQUESTS</th>
                      <th className="text-right">COST</th>
                      <th className="text-right">AVG LATENCY</th>
                      <th>HIT RATE</th>
                      <th className="text-right">TOKENS</th>
                      <th>COST/1K TOKENS</th>
                    </tr>
                  </thead>
                  <tbody>
                    {byModel.map(model => (
                      <tr key={model.name}>
                        <td><code className="code">{model.name}</code></td>
                        <td className="font-mono tabular-nums text-right">{formatNumber(model.requests)}</td>
                        <td className="font-mono tabular-nums text-right">{formatCurrency(model.cost)}</td>
                        <td className="font-mono tabular-nums text-right">{formatDuration(model.latency)}</td>
                        <td><Badge variant={model.hitRate > 0.8 ? 'success' : model.hitRate > 0.7 ? 'info' : 'warning'}>{formatPercent(model.hitRate)}</Badge></td>
                        <td className="font-mono tabular-nums text-right">{formatNumber(model.tokens)}</td>
                        <td className="font-mono tabular-nums text-right">{formatCurrency(model.cost / (model.tokens > 0 ? model.tokens / 1000 : 1))}/1k</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </CardContent>
          </Card>
        </div>
      )}

      {/* Providers Tab */}
      {activeTab === 'providers' && (
        <div className="space-y-6">
          <Card>
            <CardContent className="pt-4">
              <h3 className="font-medium mb-4">Provider Comparison</h3>
              <div className="overflow-x-auto">
                <table className="table">
                  <thead>
                    <tr>
                      <th>PROVIDER</th>
                      <th className="text-right">REQUESTS</th>
                      <th className="text-right">COST</th>
                      <th className="text-right">AVG LATENCY</th>
                      <th>HIT RATE</th>
                      <th>COST %</th>
                    </tr>
                  </thead>
                  <tbody>
                    {byProvider.map(provider => (
                      <tr key={provider.provider}>
                        <td>
                          <div className="flex items-center gap-2">
                            <div className="w-8 h-8 rounded flex items-center justify-center bg-accent/10">
                              <span className="text-accent font-bold">{provider.provider.slice(0, 3).toUpperCase()}</span>
                            </div>
                            <span className="font-medium">{provider.provider}</span>
                          </div>
                        </td>
                        <td className="font-mono tabular-nums text-right">{formatNumber(provider.requests)}</td>
                        <td className="font-mono tabular-nums text-right">{formatCurrency(provider.cost)}</td>
                        <td className="font-mono tabular-nums text-right">{formatDuration(provider.latency)}</td>
                        <td><Badge variant={provider.hitRate > 0.8 ? 'success' : 'info'}>{formatPercent(provider.hitRate)}</Badge></td>
                        <td>
                          <div className="w-32">
                            <Progress value={overview.totalCost > 0 ? (provider.cost / overview.totalCost) * 100 : 0} max={100} className="h-2" />
                          </div>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </CardContent>
          </Card>
        </div>
      )}

      {/* Cache Tab */}
      {activeTab === 'cache' && (
        <div className="space-y-6">
          <Card>
            <CardContent className="pt-4">
              <h3 className="font-medium mb-4">Cache Layer Performance</h3>
              <CachePerformanceChart 
                data={byCacheLayer.map(l => ({ layer: l.layer, hitRate: l.hitRate, color: l.color }))}
                height={350}
              />
            </CardContent>
          </Card>
          <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
            {byCacheLayer.map(layer => (
              <Card key={layer.layer}>
                <CardContent className="pt-4">
                  <div className="flex items-center justify-between mb-4">
                    <h4 className="font-medium">{layer.layer} Cache</h4>
                    <Badge variant={layer.hitRate > 0.8 ? 'success' : layer.hitRate > 0.7 ? 'info' : 'warning'}>{formatPercent(layer.hitRate)}</Badge>
                  </div>
                  <div className="space-y-3">
                    <div className="flex items-center justify-between">
                      <span className="text-body text-text-secondary">Hits</span>
                      <span className="font-mono tabular-nums text-success">{formatNumber(layer.hits)}</span>
                    </div>
                    <div className="flex items-center justify-between">
                      <span className="text-body text-text-secondary">Misses</span>
                      <span className="font-mono tabular-nums text-error">{formatNumber(layer.misses)}</span>
                    </div>
                    <div className="flex items-center justify-between">
                      <span className="text-body text-text-secondary">Latency Saved</span>
                      <span className="font-mono tabular-nums">{formatDuration(layer.latency)}</span>
                    </div>
                    <div className="flex items-center justify-between">
                      <span className="text-body text-text-secondary">Total Requests</span>
                      <span className="font-mono tabular-nums">{formatNumber(layer.hits + layer.misses)}</span>
                    </div>
                  </div>
                  <Divider className="my-3" />
                  <Progress value={layer.hitRate * 100} max={100} className="h-2" />
                </CardContent>
              </Card>
            ))}
          </div>
        </div>
      )}

      {/* Trends Tab */}
      {activeTab === 'trends' && (
        <div className="space-y-6">
          <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
            <Card>
              <CardContent className="pt-4">
                <h3 className="font-medium mb-4">Request Volume Trend</h3>
                <RequestVolumeChart
                  data={trends.requests}
                  metric="requests"
                  height={300}
                />
              </CardContent>
            </Card>
            <Card>
              <CardContent className="pt-4">
                <h3 className="font-medium mb-4">Latency Trend</h3>
                <RequestVolumeChart
                  data={trends.latency}
                  metric="latency"
                  height={300}
                />
              </CardContent>
            </Card>
            <Card>
              <CardContent className="pt-4">
                <h3 className="font-medium mb-4">Cost Trend</h3>
                <CostChart
                  data={trends.cost.map(point => ({ name: new Date(point.timestamp).toLocaleTimeString(), input: point.value, output: 0, cached: 0 }))}
                  height={300}
                />
              </CardContent>
            </Card>
            <Card>
              <CardContent className="pt-4">
                <h3 className="font-medium mb-4">Hit Rate Trend</h3>
                <RequestVolumeChart
                  data={hitRateTrend}
                  metric="requests"
                  height={300}
                />
              </CardContent>
            </Card>
          </div>
        </div>
      )}
    </div>
  )
}