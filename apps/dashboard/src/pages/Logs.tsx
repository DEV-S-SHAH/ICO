// Logs Page

import React, { useState, useMemo } from 'react'
import {
  FileText,
  Search,
  Filter,
  Download,
  ChevronLeft,
  ChevronRight,
  AlertTriangle,
  CheckCircle,
  Info,
  XCircle,
  Loader2,
  RefreshCw,
} from 'lucide-react'
import { cn } from '@/components/common'
import { formatRelativeTime } from '@/lib/formatters'
import {
  Button,
  Input,
  Badge,
  Card,
  CardContent,
  Select,
  Divider,
  EmptyState,
  LoadingSkeleton,
} from '@/components/common'

const LOG_LEVELS = [
  { value: 'debug', label: 'Debug', color: 'text-text-muted' },
  { value: 'info', label: 'Info', color: 'text-blue-400' },
  { value: 'warn', label: 'Warning', color: 'text-yellow-400' },
  { value: 'error', label: 'Error', color: 'text-red-400' },
]

const MOCK_LOGS = [
  { id: 'log-1', timestamp: '2024-01-20T14:32:15.123Z', level: 'info', service: 'cache-api', message: 'Cache hit for key sha256:abc123', metadata: { layer: 'L1', latency: 2, tenant: 'default' } },
  { id: 'log-2', timestamp: '2024-01-20T14:32:14.456Z', level: 'info', service: 'cache-api', message: 'Cache miss for key sha256:def456', metadata: { layer: 'L2', latency: 45, tenant: 'default' } },
  { id: 'log-3', timestamp: '2024-01-20T14:32:13.789Z', level: 'warn', service: 'embedding-worker', message: 'Embedding generation took longer than expected', metadata: { duration: 2340, model: 'text-embedding-3-large' } },
  { id: 'log-4', timestamp: '2024-01-20T14:32:12.234Z', level: 'error', service: 'cache-api', message: 'Failed to connect to vector store', metadata: { error: 'Connection timeout', retries: 3, store: 'qdrant' } },
  { id: 'log-5', timestamp: '2024-01-20T14:32:11.567Z', level: 'info', service: 'invalidation-service', message: 'Invalidated 42 cache entries for model gpt-4o', metadata: { model: 'gpt-4o', count: 42, trigger: 'model_update' } },
  { id: 'log-6', timestamp: '2024-01-20T14:32:10.890Z', level: 'debug', service: 'cache-api', message: 'L2 similarity search completed', metadata: { candidates: 150, threshold: 0.85, matches: 3 } },
  { id: 'log-7', timestamp: '2024-01-20T14:32:09.123Z', level: 'info', service: 'cost-tracker', message: 'Monthly cost threshold 80% reached', metadata: { current: 847.32, threshold: 1000, period: '2024-01' } },
  { id: 'log-8', timestamp: '2024-01-20T14:32:08.456Z', level: 'info', service: 'rate-limiter', message: 'Rate limit exceeded for tenant premium-user', metadata: { tenant: 'premium-user', limit: 1000, window: '1m' } },
  { id: 'log-9', timestamp: '2024-01-20T14:32:07.789Z', level: 'debug', service: 'embedding-worker', message: 'Batch embedding request received', metadata: { batchSize: 10, texts: 10 } },
  { id: 'log-10', timestamp: '2024-01-20T14:32:06.234Z', level: 'info', service: 'cache-api', message: 'Request routed to fallback model', metadata: { primary: 'gpt-4o', fallback: 'gpt-4o-mini', reason: 'latency_threshold' } },
  { id: 'log-11', timestamp: '2024-01-20T14:32:05.567Z', level: 'warn', service: 'cache-api', message: 'L3 cache layer unavailable, falling back to L2', metadata: { layer: 'L3', fallback: 'L2' } },
  { id: 'log-12', timestamp: '2024-01-20T14:32:04.890Z', level: 'info', service: 'health-check', message: 'All services healthy', metadata: { services: ['cache-api', 'embedding-worker', 'invalidation-service', 'qdrant', 'redis'] } },
]

const PAGE_SIZES = [25, 50, 100, 200]

export function Logs() {
  const [logs, setLogs] = useState(MOCK_LOGS)
  const [loading, setLoading] = useState(false)
  const [search, setSearch] = useState('')
  const [levelFilter, setLevelFilter] = useState<string>('all')
  const [serviceFilter, setServiceFilter] = useState<string>('all')
  const [sortConfig, setSortConfig] = useState<{ column: string; direction: 'asc' | 'desc' }>({ column: 'timestamp', direction: 'desc' })
  const [pagination, setPagination] = useState({ page: 1, pageSize: 50, total: MOCK_LOGS.length })
  const [expandedLog, setExpandedLog] = useState<string | null>(null)
  const [autoRefresh, setAutoRefresh] = useState(false)

  const services = useMemo(() => [...new Set(logs.map(l => l.service))], [logs])

  const filteredLogs = useMemo(() => {
    let result = [...logs]
    if (search) {
      const s = search.toLowerCase()
      result = result.filter(l => 
        l.message.toLowerCase().includes(s) || 
        l.service.toLowerCase().includes(s) ||
        JSON.stringify(l.metadata).toLowerCase().includes(s)
      )
    }
    if (levelFilter !== 'all') {
      result = result.filter(l => l.level === levelFilter)
    }
    if (serviceFilter !== 'all') {
      result = result.filter(l => l.service === serviceFilter)
    }
    result.sort((a, b) => {
      const aVal = a[sortConfig.column as keyof typeof logs[0]]
      const bVal = b[sortConfig.column as keyof typeof logs[0]]
      if (aVal < bVal) return sortConfig.direction === 'asc' ? -1 : 1
      if (aVal > bVal) return sortConfig.direction === 'asc' ? 1 : -1
      return 0
    })
    return result
  }, [logs, search, levelFilter, serviceFilter, sortConfig])

  const paginatedLogs = useMemo(() => {
    const start = (pagination.page - 1) * pagination.pageSize
    return filteredLogs.slice(start, start + pagination.pageSize)
  }, [filteredLogs, pagination])

  const handleSort = (column: string) => {
    const direction = sortConfig.column === column && sortConfig.direction === 'asc' ? 'desc' : 'asc'
    setSortConfig({ column, direction })
  }

  const handlePageChange = (page: number) => {
    setPagination({ ...pagination, page })
  }

  const handlePageSizeChange = (pageSize: number) => {
    setPagination({ ...pagination, pageSize, page: 1 })
  }

  const handleRefresh = async () => {
    setLoading(true)
    await new Promise(r => setTimeout(r, 500))
    setLoading(false)
  }

  const getLevelIcon = (level: string) => {
    switch (level) {
      case 'error': return <XCircle className="w-3 h-3 text-red-400" />
      case 'warn': return <AlertTriangle className="w-3 h-3 text-yellow-400" />
      case 'info': return <Info className="w-3 h-3 text-blue-400" />
      case 'debug': return <Loader2 className="w-3 h-3 text-text-muted" />
      default: return <Info className="w-3 h-3 text-text-muted" />
    }
  }

  const getLevelBadge = (level: string) => {
    const config = LOG_LEVELS.find(l => l.value === level)
    return <Badge variant="outline" className={config?.color || ''}>{level.toUpperCase()}</Badge>
  }

  return (
    <div className="space-y-6">
      {/* Page Header */}
      <div className="page-header">
        <div>
          <h1 className="page-title flex items-center gap-2">
            <FileText className="w-6 h-6" />
            Logs
          </h1>
          <p className="page-description">Real-time system logs and debugging information</p>
        </div>
        <div className="flex items-center gap-2">
          <Button variant="secondary" size="sm" onClick={handleRefresh} disabled={loading}>
            <RefreshCw className={`w-4 h-4 ${loading ? 'animate-spin' : ''}`} />
            Refresh
          </Button>
          <Button variant="secondary" size="sm" onClick={() => {}}>
            <Download className="w-4 h-4 mr-1" />
            Export
          </Button>
          <Switch
            checked={autoRefresh}
            onChange={setAutoRefresh}
            size="sm"
          />
          <span className="text-metadata text-text-muted">Auto-refresh</span>
        </div>
      </div>

      {/* Filters */}
      <Card>
        <CardContent className="pt-4">
          <div className="flex flex-wrap items-center gap-4">
            <div className="relative flex-1 min-w-[200px]">
              <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-text-muted" />
              <Input
                placeholder="Search logs..."
                value={search}
                onChange={(e) => setSearch(e.target.value)}
                className="pl-10"
              />
            </div>
            <Select
              value={levelFilter}
              onChange={(e) => setLevelFilter(e.target.value)}
              options={[{ value: 'all', label: 'All Levels' }, ...LOG_LEVELS]}
              className="w-auto min-w-[150px]"
            />
            <Select
              value={serviceFilter}
              onChange={(e) => setServiceFilter(e.target.value)}
              options={[{ value: 'all', label: 'All Services' }, ...services.map(s => ({ value: s, label: s }))]}
              className="w-auto min-w-[180px]"
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
        </CardContent>
      </Card>

      {/* Logs Table */}
      <Card>
        <CardContent className="p-0">
          {loading ? (
            <div className="p-4 space-y-3">
              {Array.from({ length: 5 }).map((_, i) => (
                <LoadingSkeleton key={i} variant="table-row" />
              ))}
            </div>
          ) : paginatedLogs.length === 0 ? (
            <EmptyState
              icon={<FileText className="w-12 h-12" />}
              title="No logs found"
              description="Try adjusting your filters"
            />
          ) : (
            <div className="overflow-x-auto">
              <table className="table">
                <thead>
                  <tr>
                    <th className="cursor-pointer w-36" onClick={() => handleSort('timestamp')}>
                      TIMESTAMP
                      {sortConfig.column === 'timestamp' && (
                        <span className="ml-1">{sortConfig.direction === 'asc' ? <ChevronLeft className="w-3 h-3" /> : <ChevronRight className="w-3 h-3" />}</span>
                      )}
                    </th>
                    <th className="w-20">LEVEL</th>
                    <th className="w-32 cursor-pointer" onClick={() => handleSort('service')}>
                      SERVICE
                      {sortConfig.column === 'service' && (
                        <span className="ml-1">{sortConfig.direction === 'asc' ? <ChevronLeft className="w-3 h-3" /> : <ChevronRight className="w-3 h-3" />}</span>
                      )}
                    </th>
                    <th>MESSAGE</th>
                    <th className="w-12"></th>
                  </tr>
                </thead>
                <tbody>
                  {paginatedLogs.map((log) => (
                    <>
                      <tr key={log.id} className={expandedLog === log.id ? 'bg-bg-elevated/50' : ''}>
                        <td className="font-mono text-code whitespace-nowrap">{formatRelativeTime(log.timestamp)}</td>
                        <td>{getLevelBadge(log.level)}</td>
                        <td className="font-mono text-code text-text-secondary">{log.service}</td>
                        <td className="max-w-[500px] truncate">{log.message}</td>
                        <td className="text-center">
                          <Button
                            variant="ghost"
                            size="sm"
                            onClick={() => setExpandedLog(expandedLog === log.id ? null : log.id)}
                            className="p-1"
                          >
                            {expandedLog === log.id ? <ChevronUp className="w-4 h-4" /> : <ChevronDown className="w-4 h-4" />}
                          </Button>
                        </td>
                      </tr>
                      {expandedLog === log.id && (
                        <tr key={`${log.id}-expanded`}>
                          <td colSpan={5} className="p-0">
                            <div className="bg-bg-tertiary p-4 border-t border-border-subtle">
                              <pre className="code text-sm overflow-x-auto">{JSON.stringify(log.metadata, null, 2)}</pre>
                            </div>
                          </td>
                        </tr>
                      )}
                    </>
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
                <span className="mx-2">•</span>
                {filteredLogs.length} of {logs.length} logs
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