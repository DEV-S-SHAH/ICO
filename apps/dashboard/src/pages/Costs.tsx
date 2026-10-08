// Costs / Usage Page

import { useEffect, useState, useMemo } from 'react'
import {
  DollarSign,
  TrendingUp,
  TrendingDown,
  RefreshCw,
  Calendar,
  BarChart3,
  Download,
  ChevronLeft,
  ChevronRight,
  Filter,
} from 'lucide-react'
import { cn } from '@/components/common'
import { formatNumber, formatCurrency, formatDuration, formatPercent } from '@/lib/formatters'
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
import { RequestVolumeChart, CostChart, ModelComparisonChart } from '@/components/charts'
import { useUIStore, useDataStore } from '@/lib/stores'
import { getApiClient } from '@/lib/api/client'
import { mockRequests, generateMockTimeSeries } from '@/data/mock'
import type { Request, TimeRange, PaginationState, SortState } from '@/types'

const PAGE_SIZES = [10, 25, 50, 100]

const TIME_RANGES: Array<{ value: TimeRange; label: string }> = [
  { value: '1h', label: '1H' },
  { value: '24h', label: '24H' },
  { value: '7d', label: '7D' },
  { value: '30d', label: '30D' },
]

const GROUP_BY_OPTIONS = [
  { value: 'model', label: 'By Model' },
  { value: 'provider', label: 'By Provider' },
  { value: 'endpoint', label: 'By Endpoint' },
  { value: 'time', label: 'Over Time' },
]

export function Costs() {
  const { demoMode, liveTick: requestsVersion } = useUIStore()
  const { requests, setRequests } = useDataStore()
  const [loading, setLoading] = useState(false)
  const [timeRange, setTimeRange] = useState<TimeRange>('24h')
  const [groupBy, setGroupBy] = useState<'model' | 'provider' | 'endpoint' | 'time'>('model')
  const [chartMetric, setChartMetric] = useState<'cost' | 'tokens' | 'requests'>('cost')
  const [sortConfig, setSortConfig] = useState<SortState>({ column: 'cost', direction: 'desc' })
  const [pagination, setPagination] = useState<PaginationState>({ page: 1, pageSize: 25, total: 0 })
  const [search, setSearch] = useState('')
  const [chartData, setChartData] = useState<import('@/types').TimeSeriesPoint[]>([])

  // Load requests (real API in live mode; mock only in demo mode)
  useEffect(() => {
    async function loadRequests() {
      setLoading(true)
      try {
        const api = getApiClient(demoMode)
        const res = await api.getRequests(
          { status: 'all', model: 'all', provider: 'all', cache: 'all', endpoint: 'all', timeRange, search: '' },
          { page: 1, pageSize: 200, total: 0 },
          { column: 'timestamp', direction: 'desc' }
        )
        setRequests(res.data)
        setPagination({ total: res.data.length })
        const data = await api.getTimeSeries(chartMetric, timeRange)
        setChartData(data)
      } catch (error) {
        console.error('Failed to load cost data:', error)
        if (demoMode) {
          setRequests(mockRequests)
          setPagination({ total: mockRequests.length })
          setChartData(generateMockTimeSeries(chartMetric, timeRange))
        } else {
          setRequests([])
          setPagination({ total: 0 })
          setChartData([])
        }
      } finally {
        setLoading(false)
      }
    }
    loadRequests()
  }, [demoMode, timeRange, chartMetric, setRequests, requestsVersion])

  // Filter and sort requests
  const filteredRequests = useMemo(() => {
    let result = [...requests]
    if (search) {
      const s = search.toLowerCase()
      result = result.filter(r => r.id.toLowerCase().includes(s) || r.model.toLowerCase().includes(s) || r.endpoint.toLowerCase().includes(s))
    }
    result.sort((a, b) => {
      const aVal = a[sortConfig.column as keyof Request]
      const bVal = b[sortConfig.column as keyof Request]
      if (aVal < bVal) return sortConfig.direction === 'asc' ? -1 : 1
      if (aVal > bVal) return sortConfig.direction === 'asc' ? 1 : -1
      return 0
    })
    return result
  }, [requests, search, sortConfig])

  const paginatedRequests = useMemo(() => {
    const start = (pagination.page - 1) * pagination.pageSize
    return filteredRequests.slice(start, start + pagination.pageSize)
  }, [filteredRequests, pagination])

  // Aggregated data for charts
  const aggregatedData = useMemo(() => {
    if (groupBy === 'time') return null

    const groups = new Map<string, { input: number; output: number; cached: number; requests: number; cost: number }>()
    
    filteredRequests.forEach(req => {
      let key: string
      switch (groupBy) {
        case 'model': key = req.model; break
        case 'provider': key = req.provider; break
        case 'endpoint': key = req.endpoint; break
        default: key = req.model;
      }
      
      const existing = groups.get(key) || { input: 0, output: 0, cached: 0, requests: 0, cost: 0 }
      existing.input += req.cost.input
      existing.output += req.cost.output
      existing.cached += req.cost.saved
      existing.requests += 1
      existing.cost += req.cost.total
      groups.set(key, existing)
    })

    return Array.from(groups.entries())
      .map(([name, data]) => ({ name, ...data }))
      .sort((a, b) => b.cost - a.cost)
      .slice(0, 15)
  }, [filteredRequests, groupBy])

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

  // Summary stats
  const totalCost = filteredRequests.reduce((sum, r) => sum + r.cost.total, 0)
  const totalInputCost = filteredRequests.reduce((sum, r) => sum + r.cost.input, 0)
  const totalOutputCost = filteredRequests.reduce((sum, r) => sum + r.cost.output, 0)
  const totalSaved = filteredRequests.reduce((sum, r) => sum + r.cost.saved, 0)
  const totalTokens = filteredRequests.reduce((sum, r) => sum + r.tokens.total, 0)
  const cachedTokens = filteredRequests.reduce((sum, r) => sum + r.tokens.cachedInput, 0)
  const avgCostPerRequest = filteredRequests.length > 0 ? totalCost / filteredRequests.length : 0

  return (
    <div className="space-y-6">
      {/* Page Header */}
      <div className="page-header">
        <div>
          <h1 className="page-title">Costs & Usage</h1>
          <p className="page-description">Analyze token usage, cache savings, and estimated costs across models and providers</p>
        </div>
        <div className="flex items-center gap-2">
          <Button variant="secondary" size="sm" onClick={() => window.location.reload()}>
            <RefreshCw className="w-4 h-4" />
            Refresh
          </Button>
        </div>
      </div>

      {/* Summary Cards */}
      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-5 gap-4 mb-6">
        <Card>
          <CardContent className="pt-4">
            <div className="flex items-center justify-between">
              <div>
                <p className="text-metadata text-text-muted">TOTAL SPEND</p>
                <p className="text-2xl font-semibold font-mono tabular-nums">{formatCurrency(totalCost)}</p>
              </div>
              <DollarSign className="w-8 h-8 text-text-muted/30" />
            </div>
          </CardContent>
        </Card>
        <Card>
          <CardContent className="pt-4">
            <div className="flex items-center justify-between">
              <div>
                <p className="text-metadata text-text-muted">INPUT COST</p>
                <p className="text-2xl font-semibold font-mono tabular-nums">{formatCurrency(totalInputCost)}</p>
              </div>
              <DollarSign className="w-8 h-8 text-text-muted/30" />
            </div>
          </CardContent>
        </Card>
        <Card>
          <CardContent className="pt-4">
            <div className="flex items-center justify-between">
              <div>
                <p className="text-metadata text-text-muted">OUTPUT COST</p>
                <p className="text-2xl font-semibold font-mono tabular-nums">{formatCurrency(totalOutputCost)}</p>
              </div>
              <DollarSign className="w-8 h-8 text-text-muted/30" />
            </div>
          </CardContent>
        </Card>
        <Card>
          <CardContent className="pt-4">
            <div className="flex items-center justify-between">
              <div>
                <p className="text-metadata text-text-muted">EST. SAVINGS</p>
                <p className="text-2xl font-semibold font-mono tabular-nums text-success">{formatCurrency(totalSaved)}</p>
              </div>
              <TrendingUp className="w-8 h-8 text-success/30" />
            </div>
          </CardContent>
        </Card>
        <Card>
          <CardContent className="pt-4">
            <div className="flex items-center justify-between">
              <div>
                <p className="text-metadata text-text-muted">AVG COST/REQ</p>
                <p className="text-2xl font-semibold font-mono tabular-nums">{formatCurrency(avgCostPerRequest)}</p>
              </div>
              <DollarSign className="w-8 h-8 text-text-muted/30" />
            </div>
          </CardContent>
        </Card>
      </div>

      {/* Token Stats */}
      <div className="grid grid-cols-1 sm:grid-cols-3 gap-4 mb-6">
        <Card>
          <CardContent className="pt-4">
            <div>
              <p className="text-metadata text-text-muted">TOTAL TOKENS</p>
              <p className="text-2xl font-semibold font-mono tabular-nums">{formatNumber(totalTokens)}</p>
            </div>
          </CardContent>
        </Card>
        <Card>
          <CardContent className="pt-4">
            <div>
              <p className="text-metadata text-text-muted">CACHED TOKENS</p>
              <p className="text-2xl font-semibold font-mono tabular-nums text-success">{formatNumber(cachedTokens)}</p>
            </div>
          </CardContent>
        </Card>
        <Card>
          <CardContent className="pt-4">
            <div>
              <p className="text-metadata text-text-muted">CACHE TOKEN RATE</p>
              <p className="text-2xl font-semibold font-mono tabular-nums">{totalTokens > 0 ? formatPercent(cachedTokens / totalTokens) : '0%'}</p>
            </div>
          </CardContent>
        </Card>
      </div>

      {/* Controls */}
      <div className="flex flex-wrap items-center justify-between gap-4 mb-4">
        <div className="flex items-center gap-3 flex-1">
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
          <Select
            value={groupBy}
            onChange={(e) => setGroupBy(e.target.value as typeof groupBy)}
            options={GROUP_BY_OPTIONS}
            className="w-40"
          />
          <Select
            value={chartMetric}
            onChange={(e) => setChartMetric(e.target.value as typeof chartMetric)}
            options={[
              { value: 'cost', label: 'Cost' },
              { value: 'tokens', label: 'Tokens' },
              { value: 'requests', label: 'Requests' },
            ]}
            className="w-32"
          />
        </div>
        <Input
          placeholder="Search requests..."
          value={search}
          onChange={(e) => setSearch(e.target.value)}
          leftIcon={<Filter className="w-4 h-4" />}
          className="max-w-xs"
        />
      </div>

      {/* Charts */}
      <Tabs defaultValue="overview" className="mb-6">
        <TabsList>
          <TabsTrigger value="overview">Overview</TabsTrigger>
          <TabsTrigger value="breakdown">Breakdown</TabsTrigger>
          <TabsTrigger value="trends">Trends</TabsTrigger>
        </TabsList>

        <TabsContent value="overview" className="mt-4">
          <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
            {/* Cost Over Time */}
            <Card>
              <CardContent className="pt-4">
                <div className="flex items-center justify-between mb-4">
                  <h3 className="text-section-title">COST OVER TIME</h3>
                </div>
                {loading ? (
                  <div className="h-64 flex items-center justify-center">
                    <div className="animate-spin rounded-full h-8 w-8 border-b-2 border-accent" />
                  </div>
                ) : (
                  <RequestVolumeChart data={chartData} metric={chartMetric} height={280} />
                )}
              </CardContent>
            </Card>

            {/* Cost Breakdown by Group */}
            <Card>
              <CardContent className="pt-4">
                <h3 className="text-section-title mb-4">COST BREAKDOWN</h3>
                {groupBy === 'time' ? (
                  <RequestVolumeChart data={chartData} metric="cost" height={280} />
                ) : (
                  <CostChart data={aggregatedData || []} height={280} />
                )}
              </CardContent>
            </Card>
          </div>
        </TabsContent>

        <TabsContent value="breakdown" className="mt-4">
          <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
            <Card>
              <CardContent className="pt-4">
                <h3 className="text-section-title mb-4">COST BY MODEL</h3>
                <ModelComparisonChart
                  data={aggregatedData?.map(d => ({ name: d.name, requests: d.requests, cacheHitRate: 0, cost: d.cost })) || []}
                  metric="cost"
                  height={300}
                />
              </CardContent>
            </Card>
            <Card>
              <CardContent className="pt-4">
                <h3 className="text-section-title mb-4">TOKENS BY MODEL</h3>
                <ModelComparisonChart
                  data={aggregatedData?.map(d => ({ name: d.name, requests: d.requests, cacheHitRate: 0, cost: d.input + d.output })) || []}
                  metric="cost"
                  height={300}
                />
              </CardContent>
            </Card>
          </div>
        </TabsContent>

        <TabsContent value="trends" className="mt-4">
          <Card>
            <CardContent className="pt-4">
              <h3 className="text-section-title mb-4">COST TRENDS</h3>
              <RequestVolumeChart data={chartData} metric="cost" height={300} />
            </CardContent>
          </Card>
        </TabsContent>
      </Tabs>

      {/* Requests Table */}
      <div className="flex items-center justify-between gap-4 mb-4">
        <span className="text-body text-text-secondary">
          {pagination.total.toLocaleString()} requests
        </span>
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
          ) : paginatedRequests.length === 0 ? (
            <EmptyState
              icon={<DollarSign className="w-12 h-12" />}
              title="No requests found"
              description="Try adjusting your filters or time range"
            />
          ) : (
            <div className="overflow-x-auto">
              <table className="table">
                <thead>
                  <tr>
                    <th className="cursor-pointer" onClick={() => handleSort('timestamp')}>
                      TIME
                      {sortConfig.column === 'timestamp' && (
                        <span className="ml-1">{sortConfig.direction === 'asc' ? <TrendingUp className="w-3 h-3" /> : <TrendingDown className="w-3 h-3" />}</span>
                      )}
                    </th>
                    <th className="cursor-pointer" onClick={() => handleSort('model')}>
                      MODEL
                      {sortConfig.column === 'model' && (
                        <span className="ml-1">{sortConfig.direction === 'asc' ? <TrendingUp className="w-3 h-3" /> : <TrendingDown className="w-3 h-3" />}</span>
                      )}
                    </th>
                    <th className="cursor-pointer" onClick={() => handleSort('endpoint')}>
                      ENDPOINT
                      {sortConfig.column === 'endpoint' && (
                        <span className="ml-1">{sortConfig.direction === 'asc' ? <TrendingUp className="w-3 h-3" /> : <TrendingDown className="w-3 h-3" />}</span>
                      )}
                    </th>
                    <th className="cursor-pointer text-right" onClick={() => handleSort('tokens')}>
                      TOKENS
                      {sortConfig.column === 'tokens' && (
                        <span className="ml-1">{sortConfig.direction === 'asc' ? <TrendingUp className="w-3 h-3" /> : <TrendingDown className="w-3 h-3" />}</span>
                      )}
                    </th>
                    <th className="cursor-pointer" onClick={() => handleSort('cache')}>
                      CACHE
                      {sortConfig.column === 'cache' && (
                        <span className="ml-1">{sortConfig.direction === 'asc' ? <TrendingUp className="w-3 h-3" /> : <TrendingDown className="w-3 h-3" />}</span>
                      )}
                    </th>
                    <th className="cursor-pointer text-right" onClick={() => handleSort('cost')}>
                      SPEND
                      {sortConfig.column === 'cost' && (
                        <span className="ml-1">{sortConfig.direction === 'asc' ? <TrendingUp className="w-3 h-3" /> : <TrendingDown className="w-3 h-3" />}</span>
                      )}
                    </th>
                    <th>STATUS</th>
                    <th></th>
                  </tr>
                </thead>
                <tbody>
                  {paginatedRequests.map((request) => (
                    <tr key={request.id}>
                      <td className="font-mono text-metadata text-text-muted">{request.timestamp.split('T')[1]?.split('.')[0]}</td>
                      <td className="font-mono text-code">{request.model}</td>
                      <td className="font-mono text-code">{request.endpoint}</td>
                      <td className="font-mono tabular-nums text-right">
                        {formatNumber(request.tokens.input)} / {formatNumber(request.tokens.output)}
                        {request.tokens.cachedInput > 0 && <span className="text-success ml-1">({formatNumber(request.tokens.cachedInput)} cached)</span>}
                      </td>
                      <td>
                        <Badge
                          variant={
                            request.cache.status === 'HIT' ? 'success' :
                            request.cache.status === 'MISS' ? 'warning' : 'info'
                          }
                        >
                          {request.cache.layer ? `${request.cache.layer} ${request.cache.status}` : request.cache.status}
                        </Badge>
                      </td>
                      <td className="font-mono tabular-nums text-right">{formatCurrency(request.cost.total)}</td>
                      <td><Badge variant={request.status === 'OK' ? 'success' : 'error'}>{request.status}</Badge></td>
                      <td className="text-right">
                        <Button variant="ghost" size="sm" onClick={() => useUIStore.getState().openRequestDetail(request.id)}>
                          Details
                        </Button>
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