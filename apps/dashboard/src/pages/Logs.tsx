// Logs Page

import React, { useState, useMemo, useEffect, useCallback } from 'react'
import {
  FileText,
  Search,
  Filter,
  Download,
  ChevronLeft,
  ChevronRight,
  ChevronUp,
  ChevronDown,
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
  Switch,
} from '@/components/common'
import { getApiClient } from '@/lib/api/client'
import type { Request } from '@/types'

const LOG_LEVELS = [
  { value: 'debug', label: 'Debug', color: 'text-text-muted' },
  { value: 'info', label: 'Info', color: 'text-blue-400' },
  { value: 'warn', label: 'Warning', color: 'text-yellow-400' },
  { value: 'error', label: 'Error', color: 'text-red-400' },
]

interface LogEntry {
  id: string
  timestamp: string
  level: string
  service: string
  message: string
  metadata: Record<string, unknown>
}

const toLogEntry = (req: Request): LogEntry => {
  const hit = req.cache.status === 'HIT'
  return {
    id: req.id,
    timestamp: req.timestamp,
    level: req.status === 'OK' ? 'info' : 'error',
    service: hit ? 'cache-api' : 'api-server',
    message: hit
      ? `Cache hit (${req.cache.layer}) | ${req.model} — saved ${req.cache.tokensSaved} tokens, ${req.cache.latencySaved}ms`
      : `${req.status} | ${req.model} via ${req.endpoint} — ${req.latency}ms`,
    metadata: {
      layer: req.cache.layer,
      cacheStatus: req.cache.status,
      model: req.model,
      provider: req.provider,
      latency: req.latency,
      tokensSaved: req.cache.tokensSaved,
      latencySaved: req.cache.latencySaved,
      cost: req.cost,
    },
  }
}

const PAGE_SIZES = [25, 50, 100, 200]

const DEFAULT_FILTERS = { status: 'all', model: 'all', provider: 'all', cache: 'all', endpoint: 'all', timeRange: '24h', search: '' }

export function Logs() {
  const [logs, setLogs] = useState<LogEntry[]>([])
  const [loading, setLoading] = useState(false)
  const [search, setSearch] = useState('')
  const [levelFilter, setLevelFilter] = useState<string>('all')
  const [serviceFilter, setServiceFilter] = useState<string>('all')
  const [sortConfig, setSortConfig] = useState<{ column: string; direction: 'asc' | 'desc' }>({ column: 'timestamp', direction: 'desc' })
  const [pagination, setPagination] = useState({ page: 1, pageSize: 50, total: 0 })
  const [expandedLog, setExpandedLog] = useState<string | null>(null)
  const [autoRefresh, setAutoRefresh] = useState(false)

  const loadLogs = useCallback(async () => {
    setLoading(true)
    try {
      const res = await getApiClient().getRequests(DEFAULT_FILTERS as never, { page: 1, pageSize: 200, total: 0 }, { column: 'timestamp', direction: 'desc' })
      const entries = (res.data ?? []).map(toLogEntry)
      setLogs(entries)
      setPagination(prev => ({ ...prev, total: entries.length }))
    } catch {
      setLogs([])
      setPagination(prev => ({ ...prev, total: 0 }))
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    loadLogs()
  }, [loadLogs])

  useEffect(() => {
    if (!autoRefresh) return
    const interval = setInterval(() => loadLogs(), 10000)
    return () => clearInterval(interval)
  }, [autoRefresh, loadLogs])

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

  const handleRefresh = () => {
    loadLogs()
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
          <p className="page-description">Live request activity derived from cache traffic</p>
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