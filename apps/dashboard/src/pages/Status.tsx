// Status Page

import React, { useState, useEffect } from 'react'
import {
  CheckCircle,
  AlertTriangle,
  XCircle,
  Server,
  Database,
  Zap,
  Network,
  RefreshCw,
  Clock,
  Minus,
} from 'lucide-react'
import { formatRelativeTime, formatDuration, formatPercent, formatNumber, formatCurrency } from '@/lib/formatters'
import {
  Button,
  Badge,
  Card,
  CardContent,
  Progress,
  EmptyState,
} from '@/components/common'
import { useUIStore, useDataStore } from '@/lib/stores'
import { getApiClient } from '@/lib/api/client'
import type { CacheMetrics, OverviewMetrics, ProviderMetrics, Request } from '@/types'

interface ServiceRow {
  id: string
  name: string
  type: 'core' | 'dependency'
  status: 'operational' | 'degraded' | 'outage'
  latency: number | null
  meta: string
}

const LAYER_NAMES: Record<string, string> = {
  L0b: 'Semantic Cache',
  L1: 'Exact Match',
  L2: 'Embedding Index',
  L3: 'RAG Grounding',
}

const providerStatus = (status: ProviderMetrics['status']): ServiceRow['status'] => {
  if (status === 'healthy') return 'operational'
  if (status === 'degraded') return 'degraded'
  return 'outage'
}

const getStatusIcon = (status: string) => {
  switch (status) {
    case 'operational': return <CheckCircle className="w-4 h-4 text-success" />
    case 'degraded': return <AlertTriangle className="w-4 h-4 text-warning" />
    case 'outage': return <XCircle className="w-4 h-4 text-error" />
    default: return <Minus className="w-4 h-4 text-text-muted" />
  }
}

export function Status() {
  const { connected } = useUIStore()
  const { providers, cacheMetrics, requests } = useDataStore()
  const [overview, setOverview] = useState<OverviewMetrics | null>(null)
  const [loading, setLoading] = useState(true)

  const loadOverview = async () => {
    setLoading(true)
    try {
      setOverview(await getApiClient().getOverviewMetrics())
    } catch {
      setOverview(null)
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    loadOverview()
  }, [])

  const totalRequests = requests.length
  const totalProviderErrors = providers.reduce((sum, p) => sum + p.errors, 0)
  const tokensSaved = requests.reduce((sum, r) => sum + r.cache.tokensSaved, 0)
  const avgLatency = totalRequests > 0
    ? requests.reduce((sum, r) => sum + r.latency, 0) / totalRequests
    : 0
  const hitRate = cacheMetrics?.hitRate ?? (totalRequests > 0
    ? requests.filter(r => r.cache.status === 'HIT').length / totalRequests
    : 0)

  const services: ServiceRow[] = [
    {
      id: 'api-server',
      name: 'Cache API Server',
      type: 'core',
      status: connected ? 'operational' : 'outage',
      latency: avgLatency,
      meta: `${formatNumber(totalRequests)} requests · ${formatCurrency(requests.reduce((sum, r) => sum + r.cost.total, 0))} cost`,
    },
    ...Object.entries(cacheMetrics?.layers ?? {}).filter(([key]) => LAYER_NAMES[key]).map(([key, layer]) => ({
      id: `layer-${key}`,
      name: `${key} Cache · ${LAYER_NAMES[key]}`,
      type: 'core' as const,
      status: 'operational' as const,
      latency: layer.latencySaved,
      meta: `${formatPercent(layer.hitRate)} hit rate · ${formatNumber(layer.entries)} entries · ${formatNumber(layer.requests)} requests`,
    })),
    ...providers.map(p => ({
      id: `provider-${p.id}`,
      name: p.name,
      type: 'dependency' as const,
      status: providerStatus(p.status),
      latency: p.avgLatency,
      meta: `${formatNumber(p.errors)} errors · ${p.models.length} model${p.models.length === 1 ? '' : 's'}`,
    })),
  ]

  const overallStatus = !connected ? 'outage' : providers.some(p => p.status !== 'healthy') ? 'degraded' : 'operational'

  const recentActivity = requests.slice(0, 8)

  return (
    <div className="space-y-6">
      {/* Page Header */}
      <div className="page-header">
        <div>
          <h1 className="page-title flex items-center gap-2">
            <Server className="w-6 h-6" />
            System Status
          </h1>
          <p className="page-description">Live service health derived from the running cache instance</p>
        </div>
        <div className="flex items-center gap-4">
          <div className="flex items-center gap-2 px-3 py-1 rounded-lg bg-bg-elevated border border-border-subtle">
            {getStatusIcon(overallStatus)}
            <span className="font-medium capitalize">{overallStatus}</span>
          </div>
          <Button variant="secondary" size="sm" onClick={loadOverview} disabled={loading}>
            <RefreshCw className={`w-4 h-4 ${loading ? 'animate-spin' : ''}`} />
            Refresh
          </Button>
        </div>
      </div>

      {/* Overall Status */}
      <Card className={connected ? 'border-accent/30 bg-accent/5' : 'border-error/30 bg-error/5'}>
        <CardContent className="pt-4">
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-3">
              <div className="w-16 h-16 rounded-xl bg-accent/10 flex items-center justify-center">
                {getStatusIcon(overallStatus)}
              </div>
              <div>
                <h3 className="text-section-title">
                  {overallStatus === 'operational' ? 'All Systems Operational' : overallStatus === 'degraded' ? 'Service Degraded' : 'API Server Offline'}
                </h3>
                <p className="text-body text-text-secondary">
                  {overallStatus === 'operational'
                    ? `${formatNumber(totalRequests)} requests served · ${formatCurrency(requests.reduce((sum, r) => sum + r.cost.total, 0))} total cost · ${formatNumber(tokensSaved)} tokens saved by cache`
                    : 'Check the API server connection and refresh.'}
                </p>
              </div>
            </div>
            <div className="text-right">
              <p className="text-metadata text-text-muted">Last Updated</p>
              <p className="font-mono tabular-nums">{formatRelativeTime(overview ? requests[0]?.timestamp ?? new Date().toISOString() : new Date().toISOString())}</p>
            </div>
          </div>
        </CardContent>
      </Card>

      {/* Services Grid */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
        {['core', 'dependency'].map(category => (
          <Card key={category}>
            <CardContent className="pt-4">
              <h3 className="font-medium text-text-secondary mb-4 capitalize">{category} Services</h3>
              <div className="space-y-3">
                {services.filter(s => s.type === category).map(service => (
                  <div key={service.id} className="p-3 rounded-lg border border-border-subtle hover:bg-bg-elevated/50 transition-colors">
                    <div className="flex items-center justify-between">
                      <div className="flex items-center gap-3">
                        <div className="w-10 h-10 rounded-lg bg-accent/10 flex items-center justify-center">
                          {service.type === 'core' ? <Zap className="w-5 h-5 text-accent" /> : <Network className="w-5 h-5 text-accent" />}
                        </div>
                        <div>
                          <div className="flex items-center gap-2">
                            <h4 className="font-medium">{service.name}</h4>
                            {getStatusIcon(service.status)}
                          </div>
                          <p className="text-caption text-text-muted">{service.meta}</p>
                        </div>
                      </div>
                      <div className="text-right">
                        <div className="flex items-center justify-end gap-2 text-metadata">
                          {service.latency != null && (
                            <span className="flex items-center gap-1">
                              <Clock className="w-3 h-3" />
                              {formatDuration(service.latency)}
                            </span>
                          )}
                        </div>
                        <p className="text-caption text-text-muted capitalize">{service.status}</p>
                      </div>
                    </div>
                  </div>
                ))}
              </div>
            </CardContent>
          </Card>
        ))}
      </div>

      {/* Recent Request Activity */}
      <Card>
        <CardContent className="pt-4">
          <div className="flex items-center justify-between mb-4">
            <h3 className="font-medium">Recent Request Activity</h3>
            <Badge variant="outline">{formatNumber(totalRequests)} requests</Badge>
          </div>
          {recentActivity.length === 0 ? (
            <EmptyState
              icon={<Server className="w-12 h-12" />}
              title="No request activity yet"
              description="Run a query through the playground or API to see live cache events here."
            />
          ) : (
            <div className="space-y-2">
              {recentActivity.map(req => (
                <div key={req.id} className="flex items-center gap-3 p-3 rounded-lg border border-border-subtle">
                  {req.cache.status === 'HIT'
                    ? <CheckCircle className="w-4 h-4 text-success flex-shrink-0" />
                    : <XCircle className="w-4 h-4 text-text-muted flex-shrink-0" />}
                  <Badge variant={req.cache.status === 'HIT' ? 'success' : 'neutral'}>{req.cache.status}</Badge>
                  <span className="text-caption text-text-muted">{req.cache.layer}</span>
                  <span className="font-mono text-code truncate flex-1">{req.model}</span>
                  {req.cache.tokensSaved > 0 && (
                    <span className="text-caption text-success flex-shrink-0">+{formatNumber(req.cache.tokensSaved)} tokens</span>
                  )}
                  <span className="text-caption text-text-muted flex-shrink-0">{formatDuration(req.latency)}</span>
                  <span className="text-caption text-text-muted flex-shrink-0">{formatRelativeTime(req.timestamp)}</span>
                </div>
              ))}
            </div>
          )}
        </CardContent>
      </Card>

      {/* Live Component Summary */}
      <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
        <Card>
          <CardContent className="pt-4">
            <div className="flex items-center justify-between">
              <div>
                <p className="text-metadata text-text-muted">CACHE HIT RATE</p>
                <p className="text-3xl font-semibold font-mono tabular-nums text-success">{formatPercent(hitRate)}</p>
              </div>
              <CheckCircle className="w-10 h-10 text-success/30" />
            </div>
            <Progress value={hitRate * 100} max={100} className="mt-4 h-1" />
            <p className="text-caption text-text-muted mt-2">Across {formatNumber(totalRequests)} requests in this runtime</p>
          </CardContent>
        </Card>
        <Card>
          <CardContent className="pt-4">
            <div className="flex items-center justify-between">
              <div>
                <p className="text-metadata text-text-muted">TOKENS SAVED (CACHE)</p>
                <p className="text-3xl font-semibold font-mono tabular-nums">{formatNumber(tokensSaved)}</p>
              </div>
              <Zap className="w-10 h-10 text-accent/30" />
            </div>
            <div className="mt-4 h-1" />
            <p className="text-caption text-text-muted mt-2">{formatNumber(requests.reduce((sum, r) => sum + r.cache.latencySaved, 0))}ms latency saved</p>
          </CardContent>
        </Card>
        <Card>
          <CardContent className="pt-4">
            <div className="flex items-center justify-between">
              <div>
                <p className="text-metadata text-text-muted">AVG REQUEST LATENCY</p>
                <p className="text-3xl font-semibold font-mono tabular-nums">{formatDuration(avgLatency)}</p>
              </div>
              <Database className="w-10 h-10 text-info/30" />
            </div>
            <div className="mt-4 h-1" />
            <p className="text-caption text-text-muted mt-2">{formatNumber(totalProviderErrors)} provider errors total</p>
          </CardContent>
        </Card>
      </div>
    </div>
  )
}