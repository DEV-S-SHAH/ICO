// Metrics components

import React from 'react'
import { TrendingUp, TrendingDown, Minus } from 'lucide-react'
import { cn } from '@/components/common'
import { formatNumber, formatCurrency, formatPercent } from '@/lib/formatters'
import type { MetricCardData } from '@/types'

interface MetricCardProps {
  data: MetricCardData
  className?: string
}

export function MetricCard({ data, className }: MetricCardProps) {
  const { label, value, trend, trendLabel, unit } = data

  const trendValue = typeof trend === 'number' ? trend : 0
  const isPositive = trendValue > 0
  const isNegative = trendValue < 0

  const TrendIcon = isPositive ? TrendingUp : isNegative ? TrendingDown : Minus
  const trendColor = isPositive ? 'text-success' : isNegative ? 'text-error' : 'text-text-muted'

  return (
    <div className={cn('metric-card', className)}>
      <div className="flex items-start justify-between">
        <div className="min-w-0">
          <p className="metric-label">{label}</p>
          <p className="metric-value mt-1 font-mono tabular-nums">
            {value}
            {unit && <span className="text-body font-normal text-text-secondary ml-1">{unit}</span>}
          </p>
          {trend !== undefined && trendLabel && (
            <div className={cn('metric-trend mt-2', isPositive ? 'metric-trend-positive' : isNegative ? 'metric-trend-negative' : '')}>
              <TrendIcon className={cn('w-3 h-3', trendColor)} aria-hidden="true" />
              <span className={cn(trendColor)}>
                {isPositive ? '+' : ''}{trendValue.toFixed(1)}%
              </span>
              <span className="text-text-muted">{trendLabel}</span>
            </div>
          )}
        </div>
      </div>
    </div>
  )
}

// MetricRow - a row of metric cards
interface MetricRowProps {
  metrics: MetricCardData[]
  className?: string
}

export function MetricRow({ metrics, className }: MetricRowProps) {
  return (
    <div className={cn('grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-5 gap-4', className)}>
      {metrics.map((metric, index) => (
        <MetricCard key={index} data={metric} />
      ))}
    </div>
  )
}

// Compact metric for inline use
interface CompactMetricProps {
  label: string
  value: string | number
  trend?: number
  variant?: 'default' | 'accent' | 'success' | 'warning' | 'error'
  className?: string
}

export function CompactMetric({ label, value, trend, variant = 'default', className }: CompactMetricProps) {
  const variants = {
    default: 'text-text-primary',
    accent: 'text-accent',
    success: 'text-success',
    warning: 'text-warning',
    error: 'text-error',
  }

  const isPositive = trend && trend > 0
  const isNegative = trend && trend < 0

  return (
    <div className={cn('flex items-baseline gap-2', className)}>
      <span className="text-metadata text-text-muted">{label}</span>
      <span className={cn('font-mono font-semibold tabular-nums', variants[variant])}>
        {value}
      </span>
      {trend !== undefined && (
        <span className={cn('text-metadata font-medium', isPositive ? 'text-success' : isNegative ? 'text-error' : 'text-text-muted')}>
          {isPositive ? '▲' : isNegative ? '▼' : '●'}{Math.abs(trend).toFixed(1)}%
        </span>
      )}
    </div>
  )
}

// Stat pair for detail views
interface StatPairProps {
  label: string
  value: string | number
  unit?: string
  className?: string
}

export function StatPair({ label, value, unit, className }: StatPairProps) {
  return (
    <div className={cn('flex items-baseline gap-2', className)}>
      <span className="text-body text-text-secondary">{label}</span>
      <span className="font-mono font-medium text-text-primary tabular-nums">
        {value}{unit && <span className="font-normal text-text-secondary ml-1">{unit}</span>}
      </span>
    </div>
  )
}

// Cache layer metric card
interface CacheLayerMetricProps {
  layer: string
  hitRate: number
  requests: number
  tokensSaved: number
  latencySaved: number
  entries: number
  className?: string
}

export function CacheLayerMetric({ layer, hitRate, requests, tokensSaved, latencySaved, entries, className }: CacheLayerMetricProps) {
  const layerColors: Record<string, string> = {
    L0: 'bg-indigo-500/10 border-indigo-500/30',
    L0a: 'bg-indigo-500/10 border-indigo-500/30',
    L0b: 'bg-cyan-500/10 border-cyan-500/30',
    L1: 'bg-accent/10 border-accent/30',
    L2: 'bg-info/10 border-info/30',
    L3: 'bg-warning/10 border-warning/30',
    L4: 'bg-purple-500/10 border-purple-500/30',
    L5: 'bg-emerald-500/10 border-emerald-500/30',
    LLM: 'bg-rose-500/10 border-rose-500/30',
  }

  const layerNames: Record<string, string> = {
    L0: 'DETERMINISTIC',
    L0a: 'DETERMINISTIC',
    L0b: 'EMBEDDING',
    L1: 'EXACT',
    L2: 'SEMANTIC',
    L3: 'CONTEXT',
    L4: 'RETRIEVAL',
    L5: 'PROMPT CONTEXT',
    LLM: 'GENERATION',
  }

  return (
    <div className={cn('panel p-4 relative overflow-hidden', layerColors[layer] || 'bg-accent/10 border-accent/30', className)}>
      <div className="absolute top-3 right-3 text-4xl font-bold text-accent/10 font-mono">{layer}</div>
      <div className="relative z-10 space-y-4">
        <div>
          <p className="text-metadata text-text-muted uppercase tracking-wider">{layer} {layerNames[layer] || ''}</p>
        </div>
        <div className="flex items-baseline gap-4">
          <div>
            <p className="text-2xl font-semibold text-text-primary tabular-nums">{formatPercent(hitRate)}</p>
            <p className="text-metadata text-text-muted">Hit Rate</p>
          </div>
          <div className="border-l border-border-subtle pl-4">
            <StatPair label="Requests" value={formatNumber(requests)} />
            <StatPair label="Tokens Saved" value={formatNumber(tokensSaved)} />
            <StatPair label="Latency Saved" value={`${latencySaved}ms`} />
            <StatPair label="Entries" value={formatNumber(entries)} />
          </div>
        </div>
      </div>
    </div>
  )
}

// Total cache hit rate display
interface TotalCacheHitRateProps {
  hitRate: number
  l1Rate: number
  l2Rate: number
  l3Rate: number
  className?: string
}

export function TotalCacheHitRate({ hitRate, l1Rate, l2Rate, l3Rate, className }: TotalCacheHitRateProps) {
  return (
    <div className={cn('panel p-4', className)}>
      <div className="flex items-center justify-between mb-4">
        <p className="text-section-title">TOTAL CACHE HIT RATE</p>
        <p className="text-3xl font-bold text-accent tabular-nums">{formatPercent(hitRate)}</p>
      </div>
      <div className="h-3 bg-bg-elevated rounded-full overflow-hidden">
        <div
          className="h-full bg-accent rounded-full transition-all duration-500"
          style={{ width: `${l1Rate * 100}%` }}
        />
        <div
          className="h-full bg-info rounded-full transition-all duration-500"
          style={{ width: `${l2Rate * 100}%` }}
        />
        <div
          className="h-full bg-warning rounded-full transition-all duration-500"
          style={{ width: `${l3Rate * 100}%` }}
        />
      </div>
      <div className="flex justify-between mt-2 text-metadata text-text-muted">
        <span>L1 Exact: {formatPercent(l1Rate)}</span>
        <span>L2 Semantic: {formatPercent(l2Rate)}</span>
        <span>L3 Context: {formatPercent(l3Rate)}</span>
      </div>
    </div>
  )
}