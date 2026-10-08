// Requests Page with Table, Filters, and Detail Drawer

import { useEffect, useState, useMemo, useCallback } from 'react'
import {
  Search,
  Filter,
  ChevronDown,
  ChevronUp,
  ExternalLink,
  Copy,
  Eye,
  Download,
  X,
  Loader2,
} from 'lucide-react'
import { cn } from '@/components/common'
import { formatNumber, formatDuration, formatCurrency, formatRelativeTime, formatPercent, getStatusBadgeClass, jsonStringify } from '@/lib/formatters'
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
  Tooltip,
  Dropdown,
  Table,
  TableHeader,
  TableBody,
  TableRow,
  TableHead,
  TableCell,
  Tabs,
  TabsList,
  TabsTrigger,
  TabsContent,
} from '@/components/common'
import { useUIStore, useDataStore, useSelectionStore } from '@/lib/stores'
import { getApiClient } from '@/lib/api/client'
import { mockRequests } from '@/data/mock'
import type { Request, FilterState, SortState, PaginationState, CacheStatus, RequestStatus, CacheDecision } from '@/types'

const PAGE_SIZES = [10, 25, 50, 100]

const STATUS_OPTIONS = [
  { value: 'all', label: 'All Status' },
  { value: 'OK', label: 'OK' },
  { value: 'ERROR', label: 'Error' },
  { value: 'TIMEOUT', label: 'Timeout' },
  { value: 'RATE_LIMITED', label: 'Rate Limited' },
]

const CACHE_OPTIONS = [
  { value: 'all', label: 'All Cache' },
  { value: 'HIT', label: 'Hit' },
  { value: 'MISS', label: 'Miss' },
  { value: 'SKIPPED', label: 'Skipped' },
]

const MODEL_OPTIONS = [
  { value: 'all', label: 'All Models' },
  { value: 'claude-sonnet-4.6', label: 'claude-sonnet-4.6' },
  { value: 'claude-opus-4.5', label: 'claude-opus-4.5' },
  { value: 'gpt-5', label: 'gpt-5' },
  { value: 'gpt-5-mini', label: 'gpt-5-mini' },
  { value: 'gemini-2.5-pro', label: 'gemini-2.5-pro' },
  { value: 'gemini-2.5-flash', label: 'gemini-2.5-flash' },
  { value: 'qwen-2.5-72b', label: 'qwen-2.5-72b' },
  { value: 'llama-3.1-405b', label: 'llama-3.1-405b' },
  { value: 'llama-3.1-70b', label: 'llama-3.1-70b' },
  { value: 'mistral-large-2', label: 'mistral-large-2' },
]

const PROVIDER_OPTIONS = [
  { value: 'all', label: 'All Providers' },
  { value: 'Anthropic', label: 'Anthropic' },
  { value: 'OpenAI', label: 'OpenAI' },
  { value: 'Google', label: 'Google' },
  { value: 'Alibaba', label: 'Alibaba' },
  { value: 'Meta', label: 'Meta' },
  { value: 'Mistral', label: 'Mistral' },
]

const ENDPOINT_OPTIONS = [
  { value: 'all', label: 'All Endpoints' },
  { value: '/v1/messages', label: '/v1/messages' },
  { value: '/v1/chat/completions', label: '/v1/chat/completions' },
  { value: '/v1/completions', label: '/v1/completions' },
  { value: '/v1/embeddings', label: '/v1/embeddings' },
]

export function Requests() {
  const { demoMode, liveTick, latestLiveRequest } = useUIStore()
  const {
    requests,
    requestsFilters,
    requestsPagination,
    requestsSort,
    setRequests,
    setRequestsFilters,
    setRequestsPagination,
    setRequestsSort,
  } = useDataStore()
  const { selectedRequestIds, toggleRequestSelection, selectAllRequests, clearRequestSelection } = useSelectionStore()

  const [loading, setLoading] = useState(false)
  const [showFilters, setShowFilters] = useState(false)
  const [sortConfig, setSortConfig] = useState<SortState>(requestsSort)

  // Load data (real API in live mode; mock only in demo mode)
  useEffect(() => {
    async function loadRequests() {
      if (liveTick === 0 || demoMode) setLoading(true)
      try {
        const api = getApiClient(demoMode)
        const response = await api.getRequests(requestsFilters, requestsPagination, sortConfig)
        setRequests(response.data)
        setRequestsPagination({ total: response.meta?.total || 0 })
      } catch (error) {
        console.error('Failed to load requests:', error)
        if (!demoMode) return
        // Demo mode only: mock data with client-side filtering
        let filtered = [...mockRequests]
        if (requestsFilters.status !== 'all') filtered = filtered.filter(r => r.status === requestsFilters.status)
        if (requestsFilters.model !== 'all') filtered = filtered.filter(r => r.model === requestsFilters.model)
        if (requestsFilters.provider !== 'all') filtered = filtered.filter(r => r.provider === requestsFilters.provider)
        if (requestsFilters.cache !== 'all') filtered = filtered.filter(r => r.cache.status === requestsFilters.cache)
        if (requestsFilters.endpoint !== 'all') filtered = filtered.filter(r => r.endpoint === requestsFilters.endpoint)
        if (requestsFilters.search) {
          const search = requestsFilters.search.toLowerCase()
          filtered = filtered.filter(r => r.id.toLowerCase().includes(search) || r.model.toLowerCase().includes(search))
        }
        filtered.sort((a, b) => {
          const aVal = a[sortConfig.column as keyof Request]
          const bVal = b[sortConfig.column as keyof Request]
          if (aVal < bVal) return sortConfig.direction === 'asc' ? -1 : 1
          if (aVal > bVal) return sortConfig.direction === 'asc' ? 1 : -1
          return 0
        })
        const start = (requestsPagination.page - 1) * requestsPagination.pageSize
        setRequests(filtered.slice(start, start + requestsPagination.pageSize))
        setRequestsPagination({ total: filtered.length })
      } finally {
        setLoading(false)
      }
    }
    loadRequests()
  }, [demoMode, liveTick, requestsFilters, requestsPagination.page, requestsPagination.pageSize, sortConfig, setRequests, setRequestsPagination])

  // Handle sorting
  const handleSort = useCallback((column: string) => {
    const direction = sortConfig.column === column && sortConfig.direction === 'asc' ? 'desc' : 'asc'
    setSortConfig({ column, direction })
    setRequestsSort({ column, direction })
  }, [sortConfig, setRequestsSort])

  // Handle page change
  const handlePageChange = (page: number) => {
    setRequestsPagination({ page })
  }

  // Handle page size change
  const handlePageSizeChange = (pageSize: number) => {
    setRequestsPagination({ pageSize, page: 1 })
  }

  // Handle filter changes
  const handleFilterChange = (key: keyof FilterState, value: FilterState[keyof FilterState]) => {
    setRequestsFilters({ [key]: value })
  }

  // Clear all filters
  const handleClearFilters = () => {
    setRequestsFilters({
      status: 'all',
      model: 'all',
      provider: 'all',
      cache: 'all',
      endpoint: 'all',
      timeRange: '24h',
      search: '',
    })
  }

  // Check if any filters are active
  const hasActiveFilters = useMemo(() => 
    requestsFilters.status !== 'all' ||
    requestsFilters.model !== 'all' ||
    requestsFilters.provider !== 'all' ||
    requestsFilters.cache !== 'all' ||
    requestsFilters.endpoint !== 'all' ||
    requestsFilters.search !== ''
  , [requestsFilters])

  // Selected count
  const selectedCount = selectedRequestIds.size

  // All rows on current page selected
  const allSelected = requests.length > 0 && requests.every(r => selectedRequestIds.has(r.id))

  return (
    <div className="space-y-6">
      {/* Page Header */}
      <div className="page-header">
        <div>
          <h1 className="page-title">Requests</h1>
          <p className="page-description">Browse and analyze LLM request logs with cache performance details</p>
        </div>
        <div className="flex items-center gap-2">
          <Button variant="secondary" size="sm" onClick={() => setShowFilters(!showFilters)}>
            <Filter className="w-4 h-4" />
            Filters
            {hasActiveFilters && <Badge variant="accent" className="ml-1">Active</Badge>}
          </Button>
        </div>
      </div>

      {/* Filters Bar */}
      {showFilters && (
        <Card className="space-y-4 p-4">
          <div className="flex items-center justify-between">
            <h3 className="text-body font-medium">Filters</h3>
            <Button variant="ghost" size="sm" onClick={handleClearFilters} disabled={!hasActiveFilters}>
              Clear All
            </Button>
          </div>
          <Divider />
          <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-6 gap-3">
            <Input
              placeholder="Search request ID, model, endpoint..."
              value={requestsFilters.search}
              onChange={(e) => handleFilterChange('search', e.target.value)}
              leftIcon={<Search className="w-4 h-4" />}
            />
            <Select
              value={requestsFilters.status}
              onChange={(e) => handleFilterChange('status', e.target.value as FilterState['status'])}
              options={STATUS_OPTIONS}
            />
            <Select
              value={requestsFilters.model}
              onChange={(e) => handleFilterChange('model', e.target.value as FilterState['model'])}
              options={MODEL_OPTIONS}
            />
            <Select
              value={requestsFilters.provider}
              onChange={(e) => handleFilterChange('provider', e.target.value as FilterState['provider'])}
              options={PROVIDER_OPTIONS}
            />
            <Select
              value={requestsFilters.cache}
              onChange={(e) => handleFilterChange('cache', e.target.value as FilterState['cache'])}
              options={CACHE_OPTIONS}
            />
            <Select
              value={requestsFilters.endpoint}
              onChange={(e) => handleFilterChange('endpoint', e.target.value as FilterState['endpoint'])}
              options={ENDPOINT_OPTIONS}
            />
          </div>
        </Card>
      )}

      {/* Table Toolbar */}
      <div className="flex items-center justify-between gap-4">
        <div className="flex items-center gap-3">
          {selectedCount > 0 && (
            <span className="text-body text-text-secondary">
              {selectedCount} selected
            </span>
          )}
          <span className="text-body text-text-secondary">
            {requestsPagination.total.toLocaleString()} total
          </span>
        </div>
        <div className="flex items-center gap-2">
          <select
            value={requestsPagination.pageSize}
            onChange={(e) => handlePageSizeChange(Number(e.target.value))}
            className="select w-auto px-2 py-1 text-metadata"
          >
            {PAGE_SIZES.map(size => (
              <option key={size} value={size}>{size} per page</option>
            ))}
          </select>
        </div>
      </div>

      {/* Requests Table */}
      <Card>
        <CardContent className="p-0">
          {loading ? (
            <div className="p-4 space-y-3">
              {Array.from({ length: 5 }).map((_, i) => (
                <LoadingSkeleton key={i} variant="table-row" />
              ))}
            </div>
          ) : requests.length === 0 ? (
            <EmptyState
              icon={<Search className="w-12 h-12" />}
              title="No requests found"
              description="Try adjusting your filters or search criteria"
            />
          ) : (
            <div className="overflow-x-auto">
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead className="w-10">
                      <input
                        type="checkbox"
                        checked={allSelected}
                        onChange={() => allSelected ? clearRequestSelection() : selectAllRequests(requests.map(r => r.id))}
                        className="rounded border-border-subtle text-accent focus:ring-accent"
                        aria-label="Select all"
                      />
                    </TableHead>
                    <TableHead className="cursor-pointer" onClick={() => handleSort('timestamp')}>
                      TIME
                      {sortConfig.column === 'timestamp' && (
                        <span className="ml-1">{sortConfig.direction === 'asc' ? <ChevronUp className="w-3 h-3" /> : <ChevronDown className="w-3 h-3" />}</span>
                      )}
                    </TableHead>
                    <TableHead className="cursor-pointer" onClick={() => handleSort('id')}>
                      REQUEST ID
                      {sortConfig.column === 'id' && (
                        <span className="ml-1">{sortConfig.direction === 'asc' ? <ChevronUp className="w-3 h-3" /> : <ChevronDown className="w-3 h-3" />}</span>
                      )}
                    </TableHead>
                    <TableHead className="cursor-pointer" onClick={() => handleSort('model')}>
                      MODEL
                      {sortConfig.column === 'model' && (
                        <span className="ml-1">{sortConfig.direction === 'asc' ? <ChevronUp className="w-3 h-3" /> : <ChevronDown className="w-3 h-3" />}</span>
                      )}
                    </TableHead>
                    <TableHead className="cursor-pointer" onClick={() => handleSort('provider')}>
                      PROVIDER
                      {sortConfig.column === 'provider' && (
                        <span className="ml-1">{sortConfig.direction === 'asc' ? <ChevronUp className="w-3 h-3" /> : <ChevronDown className="w-3 h-3" />}</span>
                      )}
                    </TableHead>
                    <TableHead className="cursor-pointer" onClick={() => handleSort('endpoint')}>
                      ENDPOINT
                      {sortConfig.column === 'endpoint' && (
                        <span className="ml-1">{sortConfig.direction === 'asc' ? <ChevronUp className="w-3 h-3" /> : <ChevronDown className="w-3 h-3" />}</span>
                      )}
                    </TableHead>
                    <TableHead className="cursor-pointer text-right" onClick={() => handleSort('tokens')}>
                      TOKENS
                      {sortConfig.column === 'tokens' && (
                        <span className="ml-1">{sortConfig.direction === 'asc' ? <ChevronUp className="w-3 h-3" /> : <ChevronDown className="w-3 h-3" />}</span>
                      )}
                    </TableHead>
                    <TableHead className="cursor-pointer" onClick={() => handleSort('cache')}>
                      CACHE
                      {sortConfig.column === 'cache' && (
                        <span className="ml-1">{sortConfig.direction === 'asc' ? <ChevronUp className="w-3 h-3" /> : <ChevronDown className="w-3 h-3" />}</span>
                      )}
                    </TableHead>
                    <TableHead className="cursor-pointer text-right" onClick={() => handleSort('latency')}>
                      LATENCY
                      {sortConfig.column === 'latency' && (
                        <span className="ml-1">{sortConfig.direction === 'asc' ? <ChevronUp className="w-3 h-3" /> : <ChevronDown className="w-3 h-3" />}</span>
                      )}
                    </TableHead>
                    <TableHead className="cursor-pointer text-right" onClick={() => handleSort('cost')}>
                      COST
                      {sortConfig.column === 'cost' && (
                        <span className="ml-1">{sortConfig.direction === 'asc' ? <ChevronUp className="w-3 h-3" /> : <ChevronDown className="w-3 h-3" />}</span>
                      )}
                    </TableHead>
                    <TableHead className="cursor-pointer" onClick={() => handleSort('status')}>
                      STATUS
                      {sortConfig.column === 'status' && (
                        <span className="ml-1">{sortConfig.direction === 'asc' ? <ChevronUp className="w-3 h-3" /> : <ChevronDown className="w-3 h-3" />}</span>
                      )}
                    </TableHead>
                    <TableHead className="w-12"></TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {requests.map((request, idx) => {
                    const isNewestLive = idx === 0 && latestLiveRequest && (latestLiveRequest.id === request.id || Math.abs(new Date(request.timestamp).getTime() - new Date(latestLiveRequest.timestamp).getTime()) < 15000)
                    return (
                    <TableRow
                      key={request.id}
                      onClick={() => useUIStore.getState().openRequestDetail(request.id)}
                      className={cn("cursor-pointer transition-colors duration-fast", isNewestLive && "bg-emerald-500/10 hover:bg-emerald-500/15 border-l-2 border-emerald-400")}
                      selected={selectedRequestIds.has(request.id)}
                    >
                      <TableCell>
                        <input
                          type="checkbox"
                          checked={selectedRequestIds.has(request.id)}
                          onChange={() => toggleRequestSelection(request.id)}
                          onClick={(e) => e.stopPropagation()}
                          className="rounded border-border-subtle text-accent focus:ring-accent"
                          aria-label={`Select request ${request.id}`}
                        />
                      </TableCell>
                      <TableCell className="font-mono text-metadata text-text-muted">
                        <div className="flex items-center gap-1.5">
                          {isNewestLive && (
                            <span className="inline-flex items-center px-1.5 py-0.5 rounded text-[9px] font-bold bg-emerald-500/25 text-emerald-300 border border-emerald-500/40 animate-pulse">
                              LIVE
                            </span>
                          )}
                          <span>{formatRelativeTime(request.timestamp)}</span>
                        </div>
                      </TableCell>
                      <TableCell className="font-mono text-code max-w-[180px] truncate">
                        {request.id}
                      </TableCell>
                      <TableCell className="font-mono text-code max-w-[160px] truncate">
                        {request.model}
                      </TableCell>
                      <TableCell className="text-text-secondary">{request.provider}</TableCell>
                      <TableCell className="font-mono text-code max-w-[160px] truncate">
                        {request.endpoint}
                      </TableCell>
                      <TableCell className="font-mono tabular-nums text-text-primary">
                        {formatNumber(request.tokens.input)} / {formatNumber(request.tokens.output)}
                        {request.tokens.cachedInput > 0 && (
                          <span className="ml-1 text-success">({formatNumber(request.tokens.cachedInput)} cached)</span>
                        )}
                      </TableCell>
                      <TableCell>
                        <Badge
                          variant={
                            request.cache.status === 'HIT' ? 'success' :
                            request.cache.status === 'MISS' ? 'warning' : 'info'
                          }
                          dot
                        >
                          {request.cache.layer ? `${request.cache.layer} ${request.cache.status}` : request.cache.status}
                        </Badge>
                      </TableCell>
                      <TableCell className="font-mono tabular-nums text-text-primary text-right">
                        {formatDuration(request.latency)}
                      </TableCell>
                      <TableCell className="font-mono tabular-nums text-text-primary text-right">
                        {formatCurrency(request.cost.total)}
                      </TableCell>
                      <TableCell>
                        <Badge variant={getStatusBadgeClass(request.status) as any}>{request.status}</Badge>
                      </TableCell>
                      <TableCell className="text-right">
                        <Tooltip content="View details">
                          <Button variant="ghost" size="sm" onClick={(e) => { e.stopPropagation(); useUIStore.getState().openRequestDetail(request.id); }}>
                            <Eye className="w-4 h-4" />
                          </Button>
                        </Tooltip>
                      </TableCell>
                    </TableRow>
                    )
                  })}
                </TableBody>
              </Table>
            </div>
          )}

          {/* Pagination */}
          <div className="flex items-center justify-between px-4 py-3 border-t border-border-subtle">
            <div className="flex items-center gap-2">
              <Button
                variant="ghost"
                size="sm"
                onClick={() => handlePageChange(requestsPagination.page - 1)}
                disabled={requestsPagination.page <= 1}
              >
                <ChevronLeft className="w-4 h-4" />
              </Button>
              <span className="text-body text-text-secondary">
                Page {requestsPagination.page} of {Math.ceil(requestsPagination.total / requestsPagination.pageSize)}
              </span>
              <Button
                variant="ghost"
                size="sm"
                onClick={() => handlePageChange(requestsPagination.page + 1)}
                disabled={requestsPagination.page >= Math.ceil(requestsPagination.total / requestsPagination.pageSize)}
              >
                <ChevronRight className="w-4 h-4" />
              </Button>
            </div>
            <div className="flex items-center gap-2 text-metadata text-text-muted">
              Showing {((requestsPagination.page - 1) * requestsPagination.pageSize) + 1} to {Math.min(requestsPagination.page * requestsPagination.pageSize, requestsPagination.total)} of {requestsPagination.total.toLocaleString()}
            </div>
          </div>
        </CardContent>
      </Card>
    </div>
  )
}

// Request Detail Drawer
interface RequestDetailDrawerProps {
  request: Request | null
  open: boolean
  onClose: () => void
}

export function RequestDetailDrawer({ request, open, onClose }: RequestDetailDrawerProps) {
  if (!request || !open) return null

  const cacheLayerColors: Record<string, string> = {
    L0: 'bg-indigo-500/20 border-indigo-500/30',
    L0a: 'bg-indigo-500/20 border-indigo-500/30',
    L0b: 'bg-cyan-500/20 border-cyan-500/30',
    L1: 'bg-accent/20 border-accent/30',
    L2: 'bg-info/20 border-info/30',
    L3: 'bg-warning/20 border-warning/30',
    L4: 'bg-purple-500/20 border-purple-500/30',
    L5: 'bg-emerald-500/20 border-emerald-500/30',
    LLM: 'bg-rose-500/20 border-rose-500/30',
  }
  const cacheStatusColors = { HIT: 'text-success', MISS: 'text-warning', SKIPPED: 'text-info', WRITE: 'text-info' }

  return (
    <>
      <div className="drawer-overlay" onClick={onClose} />
      <aside className="drawer flex flex-col" role="dialog" aria-labelledby="drawer-title">
        {/* Header */}
        <div className="flex items-center justify-between p-4 border-b border-border-subtle">
          <div>
            <h2 id="drawer-title" className="text-section-title">REQUEST</h2>
            <p className="text-metadata text-text-muted font-mono">{request.id}</p>
          </div>
          <Button variant="ghost" size="sm" onClick={onClose}>
            <X className="w-4 h-4" />
          </Button>
        </div>

        {/* Content */}
        <div className="flex-1 overflow-y-auto p-4 space-y-6">
          {/* Basic Info */}
          <div className="space-y-4">
            <h3 className="text-body font-medium text-text-secondary uppercase tracking-wider">Basic Info</h3>
            <div className="grid grid-cols-2 gap-3">
              <StatPair label="Timestamp" value={formatRelativeTime(request.timestamp)} />
              <StatPair label="Duration" value={formatDuration(request.latency)} />
              <StatPair label="Status" value={<Badge variant={getStatusBadgeClass(request.status) as any}>{request.status}</Badge>} />
              <StatPair label="Model" value={<code className="code">{request.model}</code>} />
              <StatPair label="Provider" value={request.provider} />
              <StatPair label="Endpoint" value={<code className="code">{request.endpoint}</code>} />
            </div>
          </div>

          <Divider />

          {/* Tokens */}
          <div className="space-y-4">
            <h3 className="text-body font-medium text-text-secondary uppercase tracking-wider">Tokens</h3>
            <div className="grid grid-cols-2 gap-3">
              <StatPair label="Input" value={formatNumber(request.tokens.input)} />
              <StatPair label="Output" value={formatNumber(request.tokens.output)} />
              <StatPair label="Total" value={formatNumber(request.tokens.total)} />
              <StatPair label="Cached Input" value={formatNumber(request.tokens.cachedInput)} />
            </div>
          </div>

          <Divider />

          {/* Cache Decision */}
          <div className="space-y-4">
            <h3 className="text-body font-medium text-text-secondary uppercase tracking-wider">Cache Decision</h3>
            {request.cacheDecision && request.cacheDecision.length > 0 ? (
              <div className="space-y-2">
                {request.cacheDecision.map((decision, index) => (
                  <div
                    key={index}
                    className={cn('p-3 rounded-lg border', cacheLayerColors[decision.layer] || 'bg-accent/20 border-accent/30')}
                  >
                    <div className="flex items-center justify-between">
                      <div className="flex items-center gap-2">
                        <span className="font-mono font-medium text-text-primary">{decision.layer}</span>
                        <Badge
                          variant={
                            decision.status === 'HIT' ? 'success' :
                            decision.status === 'MISS' ? 'warning' : 'info'
                          }
                        >
                          {decision.status}
                        </Badge>
                      </div>
                      {decision.duration && (
                        <span className="font-mono text-metadata text-text-muted">{decision.duration}ms</span>
                      )}
                    </div>
                    <div className="grid grid-cols-4 gap-4 mt-2 text-metadata">
                      {decision.similarity && (
                        <StatPair label="Similarity" value={formatPercent(decision.similarity)} />
                      )}
                      {decision.tokensSaved && (
                        <StatPair label="Tokens Saved" value={formatNumber(decision.tokensSaved)} />
                      )}
                      {decision.latencySaved && (
                        <StatPair label="Latency Saved" value={`${decision.latencySaved}ms`} />
                      )}
                    </div>
                  </div>
                ))}
              </div>
            ) : (
              <p className="text-body text-text-muted">No cache decision data available</p>
            )}
          </div>

          <Divider />

          {/* Cost */}
          <div className="space-y-4">
            <h3 className="text-body font-medium text-text-secondary uppercase tracking-wider">Cost Breakdown</h3>
            <div className="grid grid-cols-2 gap-3">
              <StatPair label="Input Cost" value={formatCurrency(request.cost.input)} />
              <StatPair label="Output Cost" value={formatCurrency(request.cost.output)} />
              <StatPair label="Total Cost" value={formatCurrency(request.cost.total)} />
              <StatPair label="Est. Saved" value={formatCurrency(request.cost.saved)} />
            </div>
          </div>

          <Divider />

          {/* Request Trace */}
          {request.trace && (
            <div className="space-y-4">
              <h3 className="text-body font-medium text-text-secondary uppercase tracking-wider">Execution Trace</h3>
              <RequestTrace trace={request.trace} />
            </div>
          )}

          <Divider />

          {/* Request/Response JSON */}
          <Tabs defaultValue="request">
            <TabsList>
              <TabsTrigger value="request">REQUEST</TabsTrigger>
              <TabsTrigger value="response">RESPONSE</TabsTrigger>
            </TabsList>
            <TabsContent value="request">
              <div className="mt-4 p-4 bg-bg-elevated rounded-lg font-mono text-code text-sm overflow-auto max-h-96">
                <pre>{jsonStringify(request.requestBody)}</pre>
              </div>
            </TabsContent>
            <TabsContent value="response">
              <div className="mt-4 p-4 bg-bg-elevated rounded-lg font-mono text-code text-sm overflow-auto max-h-96">
                <pre>{jsonStringify(request.responseBody)}</pre>
              </div>
            </TabsContent>
          </Tabs>
        </div>
      </aside>
    </>
  )
}

// StatPair for drawer
function StatPair({ label, value }: { label: string; value: React.ReactNode }) {
  return (
    <div className="flex flex-col gap-1">
      <span className="text-metadata text-text-muted">{label}</span>
      <span className="font-mono text-text-primary">{value}</span>
    </div>
  )
}

// Request Trace Component
interface RequestTraceProps {
  trace: Request['trace']
}

function RequestTrace({ trace }: RequestTraceProps) {
  if (!trace) return null

  const renderNode = (node: Request['trace'], depth = 0) => {
    if (!node) return null

    const statusIcons = {
      success: <span className="w-2 h-2 rounded-full bg-success" />,
      error: <span className="w-2 h-2 rounded-full bg-error" />,
      pending: <span className="w-2 h-2 rounded-full bg-warning animate-pulse" />,
    }

    const children = node.children?.map((child, i) => (
      <div key={i} className="ml-4 border-l border-border-subtle pl-3">
        {renderNode(child, depth + 1)}
      </div>
    ))

    return (
      <div key={node.id} className="flex items-start gap-2">
        <div className="flex items-center pt-0.5">{statusIcons[node.status]}</div>
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-2">
            <span className="font-mono text-body font-medium">{node.name}</span>
            <span className="font-mono text-metadata text-text-muted">{node.duration}ms</span>
            {node.result && <span className="text-metadata text-text-secondary">{node.result}</span>}
          </div>
          {children}
        </div>
      </div>
    )
  }

  return (
    <div className="space-y-2">
      {renderNode(trace)}
    </div>
  )
}