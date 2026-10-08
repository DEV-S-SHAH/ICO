// Analytics Page

import { useState } from 'react'
import {
  BarChart3,
  LineChart,
  PieChart,
  TrendingUp,
  TrendingDown,
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


const TIME_RANGES = [
  { value: '1h', label: 'Last Hour' },
  { value: '6h', label: 'Last 6 Hours' },
  { value: '24h', label: 'Last 24 Hours' },
  { value: '7d', label: 'Last 7 Days' },
  { value: '30d', label: 'Last 30 Days' },
  { value: '90d', label: 'Last 90 Days' },
]

const MOCK_ANALYTICS = {
  overview: {
    totalRequests: 287432,
    avgLatency: 287,
    cacheHitRate: 0.73,
    totalCost: 124.56,
    errorRate: 0.002,
    tokensUsed: 45678900,
    uniqueUsers: 1234,
    activeModels: 8,
  },
  trends: {
    requests: [1200, 1350, 1100, 1450, 1600, 1300, 1250, 1400, 1550, 1680, 1720, 1650],
    cost: [4.2, 4.8, 3.9, 5.1, 5.6, 4.5, 4.3, 4.9, 5.4, 5.8, 6.0, 5.7],
    latency: [245, 267, 234, 289, 312, 278, 256, 298, 324, 345, 332, 318],
    hitRate: [0.71, 0.72, 0.70, 0.73, 0.74, 0.72, 0.71, 0.73, 0.75, 0.76, 0.75, 0.74],
  },
  byModel: [
    { name: 'gpt-4o', requests: 98234, cost: 67.80, cacheHitRate: 0.68, tokens: 15678900 },
    { name: 'gpt-4o-mini', requests: 87562, cost: 12.40, cacheHitRate: 0.78, tokens: 8923400 },
    { name: 'claude-3.5-sonnet', requests: 45678, cost: 34.20, cacheHitRate: 0.71, tokens: 12345600 },
    { name: 'claude-3-haiku', requests: 34210, cost: 6.80, cacheHitRate: 0.82, tokens: 5678900 },
    { name: 'gpt-3.5-turbo', requests: 21456, cost: 3.36, cacheHitRate: 0.85, tokens: 3210000 },
  ],
  byProvider: [
    { provider: 'OpenAI', requests: 155252, cost: 83.56, latency: 312, hitRate: 0.72 },
    { provider: 'Anthropic', requests: 79888, cost: 41.00, latency: 256, hitRate: 0.75 },
    { provider: 'Local', requests: 52292, cost: 0, latency: 45, hitRate: 0.89 },
  ],
  byCacheLayer: [
    { layer: 'L1', hits: 12456, misses: 2345, hitRate: 0.84, latency: 2, color: '#FF6B3D' },
    { layer: 'L2', hits: 89234, misses: 34567, hitRate: 0.72, latency: 45, color: '#60A5FA' },
    { layer: 'L3', hits: 56789, misses: 45231, hitRate: 0.56, latency: 156, color: '#F59E0B' },
  ],
}

export function Analytics() {
  const [timeRange, setTimeRange] = useState('24h')
  const [activeTab, setActiveTab] = useState('overview')

  const overview = MOCK_ANALYTICS.overview
  const byModel = MOCK_ANALYTICS.byModel
  const byProvider = MOCK_ANALYTICS.byProvider
  const byCacheLayer = MOCK_ANALYTICS.byCacheLayer

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
                    <p className="text-caption text-success mt-1 flex items-center gap-1">
                      <TrendingUp className="w-3 h-3" /> +12.5% vs prev
                    </p>
                  </div>
                  <div className="w-12 h-12 rounded-lg bg-blue-500/10 flex items-center justify-center">
                    <LineChart className="w-6 h-6 text-blue-500" />
                  </div>
                </div>
                <Sparkline data={MOCK_ANALYTICS.trends.requests.map((value, i) => ({ timestamp: new Date(Date.now() - (11-i)*3600000).toISOString(), value }))} className="mt-3 h-12" color="#3B82F6" />
              </CardContent>
            </Card>
            <Card>
              <CardContent className="pt-4">
                <div className="flex items-center justify-between">
                  <div>
                    <p className="text-metadata text-text-muted">AVG LATENCY</p>
                    <p className="text-2xl font-semibold font-mono tabular-nums">{formatDuration(overview.avgLatency)}</p>
                    <p className="text-caption text-success mt-1 flex items-center gap-1">
                      <TrendingDown className="w-3 h-3" /> -8.2% vs prev
                    </p>
                  </div>
                  <div className="w-12 h-12 rounded-lg bg-green-500/10 flex items-center justify-center">
                    <BarChart3 className="w-6 h-6 text-green-500" />
                  </div>
                </div>
                <Sparkline data={MOCK_ANALYTICS.trends.latency.map((value, i) => ({ timestamp: new Date(Date.now() - (11-i)*3600000).toISOString(), value }))} className="mt-3 h-12" color="#22C55E" />
              </CardContent>
            </Card>
            <Card>
              <CardContent className="pt-4">
                <div className="flex items-center justify-between">
                  <div>
                    <p className="text-metadata text-text-muted">CACHE HIT RATE</p>
                    <p className="text-2xl font-semibold font-mono tabular-nums">{formatPercent(overview.cacheHitRate)}</p>
                    <p className="text-caption text-success mt-1 flex items-center gap-1">
                      <TrendingUp className="w-3 h-3" /> +3.1% vs prev
                    </p>
                  </div>
                  <div className="w-12 h-12 rounded-lg bg-purple-500/10 flex items-center justify-center">
                    <PieChart className="w-6 h-6 text-purple-500" />
                  </div>
                </div>
                <Sparkline data={MOCK_ANALYTICS.trends.hitRate.map((value, i) => ({ timestamp: new Date(Date.now() - (11-i)*3600000).toISOString(), value }))} className="mt-3 h-12" color="#A855F7" />
              </CardContent>
            </Card>
            <Card>
              <CardContent className="pt-4">
                <div className="flex items-center justify-between">
                  <div>
                    <p className="text-metadata text-text-muted">TOTAL COST</p>
                    <p className="text-2xl font-semibold font-mono tabular-nums">{formatCurrency(overview.totalCost)}</p>
                    <p className="text-caption text-error mt-1 flex items-center gap-1">
                      <TrendingUp className="w-3 h-3" /> +5.4% vs prev
                    </p>
                  </div>
                  <div className="w-12 h-12 rounded-lg bg-orange-500/10 flex items-center justify-center">
                    <BarChart3 className="w-6 h-6 text-orange-500" />
                  </div>
                </div>
                <Sparkline data={MOCK_ANALYTICS.trends.cost.map((value, i) => ({ timestamp: new Date(Date.now() - (11-i)*3600000).toISOString(), value }))} className="mt-3 h-12" color="#F97316" />
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
                  data={MOCK_ANALYTICS.trends.requests.map((value, i) => ({ timestamp: new Date(Date.now() - (11-i)*3600000).toISOString(), value }))}
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
                  data={byModel.map(m => ({ name: m.name, input: m.cost * 0.6, output: m.cost * 0.3, cached: m.cost * 0.1 }))}
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
                      <span className="text-body">Total Tokens</span>
                      <span className="font-mono tabular-nums">{formatNumber(overview.tokensUsed)}</span>
                    </div>
                    <Progress value={85} max={100} className="h-2" />
                  </div>
                  <div className="grid grid-cols-2 gap-4">
                    <div>
                      <p className="text-metadata text-text-muted">Prompt Tokens</p>
                      <p className="font-mono tabular-nums">{formatNumber(Math.floor(overview.tokensUsed * 0.6))}</p>
                    </div>
                    <div>
                      <p className="text-metadata text-text-muted">Completion Tokens</p>
                      <p className="font-mono tabular-nums">{formatNumber(Math.floor(overview.tokensUsed * 0.4))}</p>
                    </div>
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
                    <Badge variant="success">{formatPercent(overview.errorRate)}</Badge>
                  </div>
                  <Progress value={overview.errorRate * 100} max={1} className="h-2" />
                  <div className="grid grid-cols-3 gap-4 pt-2">
                    <div className="text-center">
                      <p className="text-2xl font-semibold font-mono tabular-nums text-error">12</p>
                      <p className="text-caption text-text-muted">Timeout</p>
                    </div>
                    <div className="text-center">
                      <p className="text-2xl font-semibold font-mono tabular-nums text-warning">8</p>
                      <p className="text-caption text-text-muted">Rate Limited</p>
                    </div>
                    <div className="text-center">
                      <p className="text-2xl font-semibold font-mono tabular-nums text-info">3</p>
                      <p className="text-caption text-text-muted">Validation</p>
                    </div>
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
                        <td className="font-mono tabular-nums text-right">{formatCurrency(model.cost / (model.tokens / 1000))}/1k</td>
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
                              {provider.provider === 'OpenAI' && <span className="text-accent font-bold">OAI</span>}
                              {provider.provider === 'Anthropic' && <span className="text-purple-400 font-bold">ANT</span>}
                              {provider.provider === 'Local' && <span className="text-green-400 font-bold">LOC</span>}
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
                            <Progress value={(provider.cost / overview.totalCost) * 100} max={100} className="h-2" />
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
                      <span className="text-body text-text-secondary">Avg Latency</span>
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
                  data={MOCK_ANALYTICS.trends.requests.map((count, i) => ({ timestamp: new Date(Date.now() - (11-i)*3600000).toISOString(), value: count }))}
                  height={300}
                />
              </CardContent>
            </Card>
            <Card>
              <CardContent className="pt-4">
                <h3 className="font-medium mb-4">Latency Trend</h3>
                <RequestVolumeChart 
                  data={MOCK_ANALYTICS.trends.latency.map((latency, i) => ({ timestamp: new Date(Date.now() - (11-i)*3600000).toISOString(), value: latency }))}
                  height={300}
                />
              </CardContent>
            </Card>
            <Card>
              <CardContent className="pt-4">
                <h3 className="font-medium mb-4">Cost Trend</h3>
                <CostChart 
                  data={MOCK_ANALYTICS.trends.cost.map((cost, i) => ({ name: `${i}h ago`, input: cost * 0.6, output: cost * 0.3, cached: cost * 0.1 }))}
                  height={300}
                />
              </CardContent>
            </Card>
            <Card>
              <CardContent className="pt-4">
                <h3 className="font-medium mb-4">Hit Rate Trend</h3>
                <RequestVolumeChart 
                  data={MOCK_ANALYTICS.trends.hitRate.map((rate, i) => ({ timestamp: new Date(Date.now() - (11-i)*3600000).toISOString(), value: rate }))}
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