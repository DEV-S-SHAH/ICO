// Models Page

import { useEffect, useState, useMemo } from 'react'
import {
  Cpu,
  RefreshCw,
  TrendingUp,
  TrendingDown,
  DollarSign,
  Zap,
  Database,
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
import { ModelComparisonChart } from '@/components/charts'
import { useUIStore, useDataStore } from '@/lib/stores'
import { getApiClient } from '@/lib/api/client'
import type { ModelMetrics, PaginationState, SortState } from '@/types'

const PAGE_SIZES = [10, 25, 50, 100]

export function Models() {
  const { liveTick } = useUIStore()
  const { models, setModels } = useDataStore()
  const [loading, setLoading] = useState(false)
  const [sortConfig, setSortConfig] = useState<SortState>({ column: 'requests', direction: 'desc' })
  const [pagination, setPagination] = useState<PaginationState>({ page: 1, pageSize: 25, total: 0 })
  const [search, setSearch] = useState('')

  // Load models
  useEffect(() => {
    async function loadModels() {
      if (liveTick === 0) setLoading(true)
      try {
        const api = getApiClient()
        const data = await api.getModels()
        setModels(data)
        setPagination(prev => ({ ...prev, total: data.length }))
      } catch {
        // keep existing data; offline indicator in header reflects state
      } finally {
        setLoading(false)
      }
    }
    loadModels()
  }, [liveTick, setModels])

  // Filter and sort models
  const filteredModels = useMemo(() => {
    let result = [...models]
    if (search) {
      const s = search.toLowerCase()
      result = result.filter(m => m.name.toLowerCase().includes(s) || m.provider.toLowerCase().includes(s))
    }
    result.sort((a, b) => {
      const aVal = a[sortConfig.column as keyof ModelMetrics]
      const bVal = b[sortConfig.column as keyof ModelMetrics]
      if (aVal < bVal) return sortConfig.direction === 'asc' ? -1 : 1
      if (aVal > bVal) return sortConfig.direction === 'asc' ? 1 : -1
      return 0
    })
    return result
  }, [models, search, sortConfig])

  const paginatedModels = useMemo(() => {
    const start = (pagination.page - 1) * pagination.pageSize
    return filteredModels.slice(start, start + pagination.pageSize)
  }, [filteredModels, pagination])

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
          <h1 className="page-title">Models</h1>
          <p className="page-description">Track model usage, cache performance, latency, and cost across all providers</p>
        </div>
        <div className="flex items-center gap-2">
          <Button variant="secondary" size="sm" onClick={() => window.location.reload()}>
            <RefreshCw className="w-4 h-4" />
            Refresh
          </Button>
        </div>
      </div>

      {/* Summary Charts */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-4 mb-6">
        <Card>
          <CardContent className="pt-4">
            <h3 className="text-section-title mb-4">CACHE HIT RATE BY MODEL</h3>
            <ModelComparisonChart
              data={models.map(m => ({ name: m.name, requests: m.requests, cacheHitRate: m.cacheHitRate, cost: m.cost }))}
              metric="cacheHitRate"
              height={250}
            />
          </CardContent>
        </Card>
        <Card>
          <CardContent className="pt-4">
            <h3 className="text-section-title mb-4">COST BY MODEL</h3>
            <ModelComparisonChart
              data={models.map(m => ({ name: m.name, requests: m.requests, cacheHitRate: m.cacheHitRate, cost: m.cost }))}
              metric="cost"
              height={250}
            />
          </CardContent>
        </Card>
      </div>

      {/* Search and Controls */}
      <div className="flex items-center justify-between gap-4 mb-4">
        <Input
          placeholder="Search models..."
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

      {/* Models Table */}
      <Card>
        <CardContent className="p-0">
          {loading ? (
            <div className="p-4 space-y-3">
              {Array.from({ length: 5 }).map((_, i) => (
                <LoadingSkeleton key={i} variant="table-row" />
              ))}
            </div>
          ) : paginatedModels.length === 0 ? (
            <EmptyState
              icon={<Cpu className="w-12 h-12" />}
              title="No models found"
              description="Try adjusting your search"
            />
          ) : (
            <div className="overflow-x-auto">
              <table className="table">
                <thead>
                  <tr>
                    <th className="cursor-pointer" onClick={() => handleSort('name')}>
                      MODEL
                      {sortConfig.column === 'name' && (
                        <span className="ml-1">{sortConfig.direction === 'asc' ? <TrendingUp className="w-3 h-3" /> : <TrendingDown className="w-3 h-3" />}</span>
                      )}
                    </th>
                    <th>PROVIDER</th>
                    <th className="cursor-pointer text-right" onClick={() => handleSort('requests')}>
                      REQUESTS
                      {sortConfig.column === 'requests' && (
                        <span className="ml-1">{sortConfig.direction === 'asc' ? <TrendingUp className="w-3 h-3" /> : <TrendingDown className="w-3 h-3" />}</span>
                      )}
                    </th>
                    <th className="cursor-pointer text-right" onClick={() => handleSort('inputTokens')}>
                      INPUT TOKENS
                      {sortConfig.column === 'inputTokens' && (
                        <span className="ml-1">{sortConfig.direction === 'asc' ? <TrendingUp className="w-3 h-3" /> : <TrendingDown className="w-3 h-3" />}</span>
                      )}
                    </th>
                    <th className="cursor-pointer text-right" onClick={() => handleSort('outputTokens')}>
                      OUTPUT TOKENS
                      {sortConfig.column === 'outputTokens' && (
                        <span className="ml-1">{sortConfig.direction === 'asc' ? <TrendingUp className="w-3 h-3" /> : <TrendingDown className="w-3 h-3" />}</span>
                      )}
                    </th>
                    <th className="cursor-pointer text-right" onClick={() => handleSort('cachedTokens')}>
                      CACHED TOKENS
                      {sortConfig.column === 'cachedTokens' && (
                        <span className="ml-1">{sortConfig.direction === 'asc' ? <TrendingUp className="w-3 h-3" /> : <TrendingDown className="w-3 h-3" />}</span>
                      )}
                    </th>
                    <th className="cursor-pointer" onClick={() => handleSort('cacheHitRate')}>
                      CACHE HIT RATE
                      {sortConfig.column === 'cacheHitRate' && (
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
                  </tr>
                </thead>
                <tbody>
                  {paginatedModels.map((model) => (
                    <tr key={model.id}>
                      <td>
                        <div className="flex items-center gap-2">
                          <Cpu className="w-4 h-4 text-text-muted" />
                          <code className="code">{model.name}</code>
                        </div>
                      </td>
                      <td className="text-text-secondary">{model.provider}</td>
                      <td className="font-mono tabular-nums text-right">{formatNumber(model.requests)}</td>
                      <td className="font-mono tabular-nums text-right">{formatNumber(model.inputTokens)}</td>
                      <td className="font-mono tabular-nums text-right">{formatNumber(model.outputTokens)}</td>
                      <td className="font-mono tabular-nums text-right text-success">{formatNumber(model.cachedTokens)}</td>
                      <td>
                        <Badge variant={model.cacheHitRate > 0.7 ? 'success' : model.cacheHitRate > 0.5 ? 'warning' : 'info'}>
                          {formatPercent(model.cacheHitRate)}
                        </Badge>
                      </td>
                      <td className="font-mono tabular-nums text-right">{formatDuration(model.avgLatency)}</td>
                      <td className="font-mono tabular-nums text-right">{formatCurrency(model.cost)}</td>
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
              {pagination.total} models
            </span>
          </div>
        </CardContent>
      </Card>
    </div>
  )
}