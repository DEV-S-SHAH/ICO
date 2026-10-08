// Endpoints Page

import React from 'react'
import {
  Globe,
  RefreshCw,
  TrendingUp,
  TrendingDown,
  Search,
  ChevronLeft,
  ChevronRight,
  Zap,
  Shield,
  AlertTriangle,
} from 'lucide-react'
import { cn } from '@/components/common'
import { formatNumber, formatDuration, formatPercent, formatCurrency } from '@/lib/formatters'
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
import type { PaginationState, SortState } from '@/types'

const PAGE_SIZES = [10, 25, 50, 100]

const ENDPOINT_DATA = [
  { path: '/v1/messages', method: 'POST', requests: 128492, avgLatency: 312, errorRate: 0.002, cost: 45.20, auth: 'Bearer', rateLimit: '1000/min' },
  { path: '/v1/chat/completions', method: 'POST', requests: 98234, avgLatency: 425, errorRate: 0.005, cost: 67.80, auth: 'Bearer', rateLimit: '500/min' },
  { path: '/v1/completions', method: 'POST', requests: 12456, avgLatency: 187, errorRate: 0.001, cost: 8.90, auth: 'Bearer', rateLimit: '2000/min' },
  { path: '/v1/embeddings', method: 'POST', requests: 45678, avgLatency: 89, errorRate: 0.0005, cost: 12.40, auth: 'Bearer', rateLimit: '3000/min' },
  { path: '/v1/rerank', method: 'POST', requests: 3421, avgLatency: 156, errorRate: 0.003, cost: 2.10, auth: 'Bearer', rateLimit: '100/min' },
  { path: '/v1/moderation', method: 'POST', requests: 892, avgLatency: 45, errorRate: 0, cost: 0.05, auth: 'Bearer', rateLimit: '5000/min' },
  { path: '/v1/cache/stats', method: 'GET', requests: 15678, avgLatency: 12, errorRate: 0, cost: 0, auth: 'API Key', rateLimit: '10000/min' },
  { path: '/v1/cache/invalidate', method: 'POST', requests: 234, avgLatency: 234, errorRate: 0.01, cost: 0, auth: 'API Key', rateLimit: '100/min' },
  { path: '/v1/health', method: 'GET', requests: 89012, avgLatency: 5, errorRate: 0, cost: 0, auth: 'None', rateLimit: 'Unlimited' },
  { path: '/v1/models', method: 'GET', requests: 3456, avgLatency: 23, errorRate: 0, cost: 0, auth: 'Bearer', rateLimit: '1000/min' },
]

export function Endpoints() {
  const { demoMode } = useUIStore()
  const [loading, setLoading] = useState(false)
  const [sortConfig, setSortConfig] = useState<SortState>({ column: 'requests', direction: 'desc' })
  const [pagination, setPagination] = useState<PaginationState>({ page: 1, pageSize: 25, total: ENDPOINT_DATA.length })
  const [search, setSearch] = useState('')

  // Filter and sort
  const filteredEndpoints = React.useMemo(() => {
    let result = [...ENDPOINT_DATA]
    if (search) {
      const s = search.toLowerCase()
      result = result.filter(e => e.path.toLowerCase().includes(s))
    }
    result.sort((a, b) => {
      const aVal = a[sortConfig.column as keyof typeof ENDPOINT_DATA[0]]
      const bVal = b[sortConfig.column as keyof typeof ENDPOINT_DATA[0]]
      if (aVal < bVal) return sortConfig.direction === 'asc' ? -1 : 1
      if (aVal > bVal) return sortConfig.direction === 'asc' ? 1 : -1
      return 0
    })
    return result
  }, [search, sortConfig])

  const paginatedEndpoints = React.useMemo(() => {
    const start = (pagination.page - 1) * pagination.pageSize
    return filteredEndpoints.slice(start, start + pagination.pageSize)
  }, [filteredEndpoints, pagination])

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
          <h1 className="page-title flex items-center gap-2">
            <Globe className="w-6 h-6" />
            Endpoints
          </h1>
          <p className="page-description">Monitor API endpoint performance, usage, and health</p>
        </div>
        <div className="flex items-center gap-2">
          <Button variant="secondary" size="sm" onClick={() => window.location.reload()}>
            <RefreshCw className="w-4 h-4" />
            Refresh
          </Button>
        </div>
      </div>

      {/* Summary Stats */}
      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4 mb-6">
        <Card>
          <CardContent className="pt-4">
            <div className="flex items-center justify-between">
              <div>
                <p className="text-metadata text-text-muted">TOTAL ENDPOINTS</p>
                <p className="text-2xl font-semibold font-mono tabular-nums">{ENDPOINT_DATA.length}</p>
              </div>
              <Globe className="w-8 h-8 text-text-muted/30" />
            </div>
          </CardContent>
        </Card>
        <Card>
          <CardContent className="pt-4">
            <div className="flex items-center justify-between">
              <div>
                <p className="text-metadata text-text-muted">TOTAL REQUESTS</p>
                <p className="text-2xl font-semibold font-mono tabular-nums">{formatNumber(ENDPOINT_DATA.reduce((sum, e) => sum + e.requests, 0))}</p>
              </div>
              <Globe className="w-8 h-8 text-text-muted/30" />
            </div>
          </CardContent>
        </Card>
        <Card>
          <CardContent className="pt-4">
            <div className="flex items-center justify-between">
              <div>
                <p className="text-metadata text-text-muted">AVG LATENCY</p>
                <p className="text-2xl font-semibold font-mono tabular-nums">
                  {formatDuration(ENDPOINT_DATA.reduce((sum, e) => sum + e.avgLatency, 0) / ENDPOINT_DATA.length)}
                </p>
              </div>
              <Zap className="w-8 h-8 text-text-muted/30" />
            </div>
          </CardContent>
        </Card>
        <Card>
          <CardContent className="pt-4">
            <div className="flex items-center justify-between">
              <div>
                <p className="text-metadata text-text-muted">TOTAL COST</p>
                <p className="text-2xl font-semibold font-mono tabular-nums">{formatCurrency(ENDPOINT_DATA.reduce((sum, e) => sum + e.cost, 0))}</p>
              </div>
              <Shield className="w-8 h-8 text-text-muted/30" />
            </div>
          </CardContent>
        </Card>
      </div>

      {/* Search and Controls */}
      <div className="flex items-center justify-between gap-4 mb-4">
        <Input
          placeholder="Search endpoints..."
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

      {/* Endpoints Table */}
      <Card>
        <CardContent className="p-0">
          {loading ? (
            <div className="p-4 space-y-3">
              {Array.from({ length: 5 }).map((_, i) => (
                <LoadingSkeleton key={i} variant="table-row" />
              ))}
            </div>
          ) : paginatedEndpoints.length === 0 ? (
            <EmptyState
              icon={<Globe className="w-12 h-12" />}
              title="No endpoints found"
              description="Try adjusting your search"
            />
          ) : (
            <div className="overflow-x-auto">
              <table className="table">
                <thead>
                  <tr>
                    <th className="cursor-pointer" onClick={() => handleSort('path')}>
                      ENDPOINT
                      {sortConfig.column === 'path' && (
                        <span className="ml-1">{sortConfig.direction === 'asc' ? <TrendingUp className="w-3 h-3" /> : <TrendingDown className="w-3 h-3" />}</span>
                      )}
                    </th>
                    <th>METHOD</th>
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
                    <th className="cursor-pointer" onClick={() => handleSort('errorRate')}>
                      ERROR RATE
                      {sortConfig.column === 'errorRate' && (
                        <span className="ml-1">{sortConfig.direction === 'asc' ? <TrendingUp className="w-3 h-3" /> : <TrendingDown className="w-3 h-3" />}</span>
                      )}
                    </th>
                    <th className="cursor-pointer text-right" onClick={() => handleSort('cost')}>
                      COST
                      {sortConfig.column === 'cost' && (
                        <span className="ml-1">{sortConfig.direction === 'asc' ? <TrendingUp className="w-3 h-3" /> : <TrendingDown className="w-3 h-3" />}</span>
                      )}
                    </th>
                    <th>AUTH</th>
                    <th>RATE LIMIT</th>
                    <th>STATUS</th>
                  </tr>
                </thead>
                <tbody>
                  {paginatedEndpoints.map((endpoint) => (
                    <tr key={endpoint.path}>
                      <td>
                        <code className="code">{endpoint.method} {endpoint.path}</code>
                      </td>
                      <td>
                        <Badge variant="info">{endpoint.method}</Badge>
                      </td>
                      <td className="font-mono tabular-nums text-right">{formatNumber(endpoint.requests)}</td>
                      <td className="font-mono tabular-nums text-right">{formatDuration(endpoint.avgLatency)}</td>
                      <td>
                        <Badge variant={endpoint.errorRate > 0.01 ? 'error' : endpoint.errorRate > 0 ? 'warning' : 'success'}>
                          {formatPercent(endpoint.errorRate)}
                        </Badge>
                      </td>
                      <td className="font-mono tabular-nums text-right">{formatCurrency(endpoint.cost)}</td>
                      <td className="text-text-secondary font-mono text-code">{endpoint.auth}</td>
                      <td className="text-text-secondary font-mono text-code">{endpoint.rateLimit}</td>
                      <td>
                        <Badge variant="success" dot>Healthy</Badge>
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
          </div>
        </CardContent>
      </Card>
    </div>
  )
}