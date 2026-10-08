// Formatting utilities for the dashboard

export function formatNumber(num: number, decimals = 0): string {
  if (num >= 1e9) {
    return (num / 1e9).toFixed(decimals) + 'B'
  }
  if (num >= 1e6) {
    return (num / 1e6).toFixed(decimals) + 'M'
  }
  if (num >= 1e3) {
    return (num / 1e3).toFixed(decimals) + 'K'
  }
  return num.toLocaleString(undefined, { minimumFractionDigits: decimals, maximumFractionDigits: decimals })
}

export function formatCurrency(amount: number, currency = 'USD', decimals = 2): string {
  return new Intl.NumberFormat('en-US', {
    style: 'currency',
    currency,
    minimumFractionDigits: decimals,
    maximumFractionDigits: decimals,
  }).format(amount)
}

export function formatDuration(ms: number): string {
  if (ms < 1000) {
    return `${ms}ms`
  }
  if (ms < 60000) {
    return `${(ms / 1000).toFixed(1)}s`
  }
  if (ms < 3600000) {
    return `${(ms / 60000).toFixed(1)}m`
  }
  return `${(ms / 3600000).toFixed(1)}h`
}

export function formatTimestamp(isoString: string, options?: Intl.DateTimeFormatOptions): string {
  const date = new Date(isoString)
  return date.toLocaleString(undefined, {
    year: 'numeric',
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
    second: '2-digit',
    hour12: false,
    ...options,
  })
}

export function formatRelativeTime(isoString: string): string {
  const date = new Date(isoString)
  const now = new Date()
  const diffMs = now.getTime() - date.getTime()
  const diffSec = Math.floor(diffMs / 1000)
  const diffMin = Math.floor(diffSec / 60)
  const diffHour = Math.floor(diffMin / 60)
  const diffDay = Math.floor(diffHour / 24)

  if (diffSec < 60) return 'just now'
  if (diffMin < 60) return `${diffMin}m ago`
  if (diffHour < 24) return `${diffHour}h ago`
  if (diffDay < 7) return `${diffDay}d ago`
  return formatTimestamp(isoString, { month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit' })
}

export function formatPercent(value: number, decimals = 1): string {
  return `${(value * 100).toFixed(decimals)}%`
}

export function formatBytes(bytes: number): string {
  if (bytes === 0) return '0 B'
  const k = 1024
  const sizes = ['B', 'KB', 'MB', 'GB', 'TB']
  const i = Math.floor(Math.log(bytes) / Math.log(k))
  return `${parseFloat((bytes / Math.pow(k, i)).toFixed(2))} ${sizes[i]}`
}

export function formatTokens(tokens: number): string {
  return formatNumber(tokens)
}

export function formatModelName(name: string): string {
  return name
    .replace(/-/g, ' ')
    .replace(/\b\w/g, c => c.toUpperCase())
}

export function formatCacheLayer(layer: string): string {
  return layer.toUpperCase()
}

export function formatCacheStatus(status: string): string {
  return status.toUpperCase()
}

export function formatRequestStatus(status: string): string {
  return status.toUpperCase()
}

export function truncate(str: string, length: number): string {
  if (str.length <= length) return str
  return str.slice(0, length - 1) + '…'
}

export function jsonStringify(obj: unknown, indent = 2): string {
  try {
    return JSON.stringify(obj, null, indent)
  } catch {
    return String(obj)
  }
}

export function parseJsonSafe(str: string): unknown {
  try {
    return JSON.parse(str)
  } catch {
    return str
  }
}

export function getStatusColor(status: string): string {
  switch (status.toLowerCase()) {
    case 'ok':
    case 'hit':
    case 'success':
    case 'healthy':
    case 'completed':
      return 'success'
    case 'warning':
    case 'degraded':
    case 'pending':
    case 'processing':
      return 'warning'
    case 'error':
    case 'miss':
    case 'failed':
    case 'timeout':
    case 'rate_limited':
    case 'down':
      return 'error'
    case 'skipped':
      return 'info'
    default:
      return 'neutral'
  }
}

export function getStatusBadgeClass(status: string): string {
  const color = getStatusColor(status)
  return `badge-${color}`
}