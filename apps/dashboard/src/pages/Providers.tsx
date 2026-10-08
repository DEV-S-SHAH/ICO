// Providers Page

import { useEffect, useState } from 'react'
import {
  Server,
  RefreshCw,
  TrendingUp,
  TrendingDown,
  AlertCircle,
  CheckCircle,
  AlertTriangle,
  XCircle,
  Zap,
  Search,
  ChevronLeft,
  ChevronRight,
} from 'lucide-react'
import { cn } from '@/components/common'
import { formatNumber, formatPercent, formatDuration, formatCurrency } from '@/lib/formatters'
import {
  Button,
  Input,
  Badge,
  Card,
  CardContent,
  Divider,
  EmptyState,
  LoadingSkeleton,
  Select,
} from '@/components/common'
import { useUIStore, useDataStore } from '@/lib/stores'
import { getApiClient } from '@/lib/api/client'
import { mockProviders } from '@/data/mock'
import type { ProviderMetrics, PaginationState, SortState } from '@/types'

const PAGE_SIZES = [10, 25, 50, 100]

const STATUS_ICONS = {
  healthy: CheckCircle,
  degraded: AlertTriangle,
  down: XCircle,
}

const STATUS_COLORS = {
  healthy: 'text-success',
  degraded: 'text-warning',
  down: 'text-error',
}

const STATUS_BADGES = {
  healthy: 'success' as const,
  degraded: 'warning' as const,
  down: 'error' as const,
}

export function Providers() {
  const { demoMode, liveTick } = useUIStore()
  const { providers, setProviders } = useDataStore()
  const [loading, setLoading] = useState(false)
  const [sortConfig, setSortConfig] = useState<SortState>({ column: 'requests', direction: 'desc' })
  const [pagination, setPagination] = useState<PaginationState>({ page: 1, pageSize: 25, total: 0 })
  const [search, setSearch] = useState('')

  // Load providers
  useEffect(() => {
    async function loadProviders() {
      if (liveTick === 0 || demoMode) setLoading(true)
      try {
        const api = getApiClient(demoMode)
        const data = await api.getProviders()
        setProviders(data)
        setPagination({ total: data.length })
      } catch {
        if (!demoMode) return
        setProviders(mockProviders)
        setPagination({ total: mockProviders.length })
      } finally {
        setLoading(false)
      }
    }
    loadProviders()
  }, [demoMode, liveTick, setProviders])

  // Filter and sort
  const filteredProviders = React.useMemo(() => {
    let result = [...providers]
    if (search) {
      const s = search.toLowerCase()
      result = result.filter(p => p.name.toLowerCase().includes(s))
    }
    result.sort((a, b) => {
      const aVal = a[sortConfig.column as keyof ProviderMetrics]
      const bVal = b[sortConfig.column as keyof ProviderMetrics]
      if (aVal < bVal) return sortConfig.direction === 'asc' ? -1 : 1
      if (aVal > bVal) return sortConfig.direction === 'asc' ? 1 : -1
      return 0
    })
    return result
  }, [providers, search, sortConfig])

  const paginatedProviders = React.useMemo(() => {
    const start = (pagination.page - 1) * pagination.pageSize
    return filteredProviders.slice(start, start + pagination.pageSize)
  }, [filteredProviders, pagination])

  // Handle sort
  const handleSort = (column: string) => {
    const direction = sortConfig.column === column && sortConfig.direction === 'asc' ? 'desc' : 'asc'
    setSortConfig({ column, direction })
  }

  // Handle page change
  const handlePageChange = (page: number) => {
    setPagination({ ...pagination, page })
  }

  // Handle page size change
  const handlePageSizeChange = (pageSize: number) => {
    setPagination({ ...pagination, pageSize, page: 1 })
  }

  return (
    <div className="space-y-6">
      {/* Page Header */}
      <div className="page-header">
        <div>
          <h1 className="page-title">Providers</h1>
          <p className="page-description">Monitor LLM provider health, performance, and model availability</p>
        </div>
        <div className="flex items-center gap-2">
          <Button variant="secondary" size="sm" onClick={() => window.location.reload()}>
            <RefreshCw className="w-4 h-4" />
            Refresh
          </Button>
        </div>
      </div>

      {/* Provider Cards Grid */}
      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4 mb-6">
        {providers.map((provider) => {
          const StatusIcon = STATUS_ICONS[provider.status]
          const statusColor = STATUS_COLORS[provider.status]
          const statusBadge = STATUS_BADGES[provider.status]

          return (
            <Card key={provider.id} className="p-4">
              <div className="flex items-start justify-between mb-4">
                <div className="flex items-center gap-3">
                  <div className="w-10 h-10 rounded-lg bg-accent/10 flex items-center justify-center">
                    <Server className="w-5 h-5 text-accent" />
                  </div>
                  <div>
                    <h3 className="font-medium">{provider.name}</h3>
                    <p className="text-metadata text-text-muted">{provider.models.length} models</p>
                  </div>
                </div>
                <Badge variant={statusBadge} dot>{provider.status}</Badge>
              </div>

              <Divider />

              <div className="space-y-3">
                <div className="grid grid-cols-2 gap-3">
                  <div>
                    <p className="text-metadata text-text-muted">Requests</p>
                    <p className="font-mono font-medium tabular-nums">{formatNumber(provider.requests)}</p>
                  </div>
                  <div>
                    <p className="text-metadata text-text-muted">Avg Latency</p>
                    <p className="font-mono font-medium tabular-nums">{formatDuration(provider.avgLatency)}</p>
                  </div>
                  <div>
                    <p className="text-metadata text-text-muted">Cost</p>
                    <p className="font-mono font-medium tabular-nums">{formatCurrency(provider.cost)}</p>
                  </div>
                  <div>
                    <p className="text-metadata text-text-muted">Error Rate</p>
                    <p className="font-mono font-medium tabular-nums">{formatPercent(provider.errorRate)}</p>
                  </div>
                </div>

                <div className="flex items-center gap-2 text-metadata">
                  <span className="text-text-muted">Models:</span>
                  <span className="font-mono text-text-primary">{provider.models.join(', ')}</span>
                </div>
              </div>
            </Card>
          )
        })}
      </div>

      {/* Detailed Table */}
      <div className="flex items-center justify-between gap-4 mb-4">
        <Input
          placeholder="Search providers..."
          value={search}
          onChange={(e) => setSearch(e.target.value)}
          leftIcon={<Search className="w-4 h-4" />}
          className="max-w-md"
        />
        <div className="flex items-center gap-2">
          <select
            value={pagination.pageSize}
            onChange={(e) => handlePageSizeChange(Number(e.target.value))}
            className="select w-auto px-2 py-1 text-metadata"
          >
            {PAGE_SIZES.map(size => (
              <option key={size} value={size}>{size} per page</option>
            ))}
          </select>
        </div>
      </div>

      <Card>
        <CardContent className="p-0">
          {loading ? (
            <div className="p-4 space-y-3">
              {Array.from({ length: 5 }).map((_, i) => (
                <LoadingSkeleton key={i} variant="table-row" />
              ))}
            </div>
          ) : paginatedProviders.length === 0 ? (
            <EmptyState
              icon={<Server className="w-12 h-12" />}
              title="No providers found"
              description="Try adjusting your search"
            />
          ) : (
            <div className="overflow-x-auto">
              <table className="table">
                <thead>
                  <tr>
                    <th>PROVIDER</th>
                    <th className="cursor-pointer" onClick={() => handleSort('status')}>
                      STATUS
                      {sortConfig.column === 'status' && (
                        <span className="ml-1">{sortConfig.direction === 'asc' ? <TrendingUp className="w-3 h-3" /> : <TrendingDown className="w-3 h-3" />}</span>
                      )}
                    </th>
                    <th>MODELS</th>
                    <th className="cursor-pointer text-right" onClick={() => handleSort('requests')}>
                      REQUESTS
                      {sortConfig.column === 'requests' && (
                        <span className="ml-1">{sortConfig.direction === 'asc' ? <TrendingUp className="w-3 h-3" /> : <TrendingDown className="w-3 h-3" />}</span>
                      )}
                    </th>
                    <th className="cursor-pointer text-right" onClick={() => handleSort('avgLatency')}>
                      AVG LATENCY
                      {sortConfig.column === 'avgLatency' && (
                        <span className="ml-1">{sortConfig.direction === 'asc' ? <TrendingUp className="w-3 h-3" /> : <TrendingDown className="w-3 h-3" />}</span>
                      )}
                    </th>
                    <th className="cursor-pointer text-right" onClick={() => handleSort('cost')}>
                      COST
                      {sortConfig.column === 'cost' && (
                        <span className="ml-1">{sortConfig.direction === 'asc' ? <TrendingUp className="w-3 h-3" /> : <TrendingDown className="w-3 h-3" />}</span>
                      )}
                    </th>
                    <th className="cursor-pointer text-right" onClick={() => handleSort('errors')}>
                      ERRORS
                      {sortConfig.column === 'errors' && (
                        <span className="ml-1">{sortConfig.direction === 'asc' ? <TrendingUp className="w-3 h-3" /> : <TrendingDown className="w-3 h-3" />}</span>
                      )}
                    </th>
                    <th className="cursor-pointer" onClick={() => handleSort('errorRate')}>
                      ERROR RATE
                      {sortConfig.column === 'errorRate' && (
                        <span className="ml-1">{sortConfig.direction === 'asc' ? <TrendingUp className="w-3 h-3" /> : <TrendingDown className="w-3 h-3" />}</span>
                      )}
                    </th>
                  </tr>
                </thead>
                <tbody>
                  {paginatedProviders.map((provider) => {
                    const StatusIcon = STATUS_ICONS[provider.status]
                    const statusColor = STATUS_COLORS[provider.status]
                    const statusBadge = STATUS_BADGES[provider.status]

                    return (
                      <tr key={provider.id}>
                        <td>
                          <div className="flex items-center gap-2">
                            <Server className="w-4 h-4 text-text-muted" />
                            <span className="font-medium">{provider.name}</span>
                          </div>
                        </td>
                        <td>
                          <Badge variant={statusBadge} dot>
                            <StatusIcon className={cn('w-3 h-3', statusColor)} />
                            {provider.status}
                          </Badge>
                        </td>
                        <td className="text-text-secondary">{provider.models.join(', ')}</td>
                        <td className="font-mono tabular-nums text-right">{formatNumber(provider.requests)}</td>
                        <td className="font-mono tabular-nums text-right">{formatDuration(provider.avgLatency)}</td>
                        <td className="font-mono tabular-nums text-right">{formatCurrency(provider.cost)}</td>
                        <td className="font-mono tabular-nums text-right text-error">{formatNumber(provider.errors)}</td>
                        <td>
                          <Badge variant={provider.errorRate > 0.01 ? 'error' : provider.errorRate > 0 ? 'warning' : 'success'}>
                            {formatPercent(provider.errorRate)}
                          </Badge>
                        </td>
                      </tr>
                    )
                  })}
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
                onClick={() => handlePageChange(pagination.page - 1)}
                disabled={pagination.page <= 1}
              >
                <ChevronLeft className="w-4 h-4" />
              </Button>
              <span className="text-body text-text-secondary">
                Page {pagination.page} of {Math.ceil(pagination.total / pagination.pageSize)}
              </span>
              <Button
                variant="ghost"
                size="sm"
                onClick={() => handlePageChange(pagination.page + 1)}
                disabled={pagination.page >= Math.ceil(pagination.total / pagination.pageSize)}
              >
                <ChevronRight className="w-4 h-4" />
              </Button>
            </div>
            <span className="text-metadata text-text-muted">
              {pagination.total} providers
            </span>
          </div>
        </CardContent>
      </Card>
    </div>
  )
}