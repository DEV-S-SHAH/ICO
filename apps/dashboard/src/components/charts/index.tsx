// Chart components using Recharts

import React from 'react'
import {
  AreaChart,
  Area,
  BarChart,
  Bar,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  ResponsiveContainer,
  Legend,
} from 'recharts'
import { cn } from '@/components/common'
import type { TimeSeriesPoint } from '@/types'

// Custom tooltip formatter
const CustomTooltip = ({ active, payload, label }: { active?: boolean; payload?: Array<{ value: number; name: string; color: string }>; label?: string }) => {
  if (!active || !payload || !payload.length) return null

  return (
    <div className="chart-tooltip">
      <p className="text-metadata text-text-muted mb-2">{label}</p>
      {payload.map((entry, index) => (
        <p key={index} className="flex items-center gap-2 text-body" style={{ color: entry.color }}>
          <span className="w-2 h-2 rounded-full" style={{ backgroundColor: entry.color }} />
          <span>{entry.name}: </span>
          <span className="font-mono font-medium tabular-nums">{entry.value.toLocaleString()}</span>
        </p>
      ))}
    </div>
  )
}

// Chart container wrapper
interface ChartContainerProps {
  children: React.ReactNode
  className?: string
  height?: number
}

export function ChartContainer({ children, className, height = 300 }: ChartContainerProps) {
  return (
    <div className={cn('panel p-4', className)} style={{ height }}>
      <ResponsiveContainer width="100%" height="100%">
        {children}
      </ResponsiveContainer>
    </div>
  )
}

// Request Volume Chart
interface RequestVolumeChartProps {
  data: TimeSeriesPoint[]
  metric: 'requests' | 'tokens' | 'cost' | 'latency'
  className?: string
  height?: number
}

export function RequestVolumeChart({ data, metric, className, height = 300 }: RequestVolumeChartProps) {
  const metricColors = {
    requests: '#FF6B3D',
    tokens: '#60A5FA',
    cost: '#22C55E',
    latency: '#F59E0B',
  }

  const formatValue = (value: number) => {
    switch (metric) {
      case 'cost':
        return value.toFixed(2)
      case 'latency':
        return `${value.toFixed(0)}ms`
      default:
        return value.toLocaleString()
    }
  }

  return (
    <ChartContainer className={className} height={height}>
      <AreaChart data={data} margin={{ top: 10, right: 10, left: 0, bottom: 0 }}>
        <defs>
          <linearGradient id={`gradient-${metric}`} x1="0" y1="0" x2="0" y2="1">
            <stop offset="5%" stopColor={metricColors[metric]} stopOpacity={0.3} />
            <stop offset="95%" stopColor={metricColors[metric]} stopOpacity={0} />
          </linearGradient>
        </defs>
        <CartesianGrid strokeDasharray="3 3" stroke="#242428" vertical={false} />
        <XAxis
          dataKey="timestamp"
          tickFormatter={(value) => new Date(value).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })}
          tick={{ fill: '#71717A', fontSize: 11, fontFamily: 'JetBrains Mono, monospace' }}
          axisLine={{ stroke: '#1B1B1F' }}
          tickLine={false}
          interval="preserveStartEnd"
        />
        <YAxis
          tickFormatter={formatValue}
          tick={{ fill: '#71717A', fontSize: 11, fontFamily: 'JetBrains Mono, monospace' }}
          axisLine={false}
          tickLine={false}
          dy={-10}
        />
        <Tooltip content={<CustomTooltip />} />
        <Area
          type="monotone"
          dataKey="value"
          stroke={metricColors[metric]}
          strokeWidth={1.5}
          fillOpacity={1}
          fill={`url(#gradient-${metric})`}
        />
      </AreaChart>
    </ChartContainer>
  )
}

// Cost Chart - stacked bar chart
interface CostChartProps {
  data: Array<{ name: string; input: number; output: number; cached: number }>
  className?: string
  height?: number
}

export function CostChart({ data, className, height = 300 }: CostChartProps) {
  return (
    <ChartContainer className={className} height={height}>
      <BarChart data={data} margin={{ top: 10, right: 10, left: 0, bottom: 0 }} layout="vertical">
        <CartesianGrid strokeDasharray="3 3" stroke="#242428" horizontal={false} />
        <XAxis
          type="number"
          tickFormatter={(value) => `$${value.toFixed(2)}`}
          tick={{ fill: '#71717A', fontSize: 11, fontFamily: 'JetBrains Mono, monospace' }}
          axisLine={false}
          tickLine={false}
          dy={-10}
        />
        <YAxis
          dataKey="name"
          type="category"
          width={140}
          tick={{ fill: '#A1A1AA', fontSize: 12, fontFamily: 'Inter, system-ui' }}
          axisLine={false}
          tickLine={false}
        />
        <Tooltip content={<CustomTooltip />} />
        <Legend wrapperStyle={{ paddingTop: 20 }} />
        <Bar dataKey="input" stackId="a" fill="#EF4444" name="Input" radius={[0, 4, 4, 0]} />
        <Bar dataKey="output" stackId="a" fill="#F59E0B" name="Output" radius={[0, 4, 4, 0]} />
        <Bar dataKey="cached" stackId="a" fill="#22C55E" name="Cached" radius={[0, 4, 4, 0]} />
      </BarChart>
    </ChartContainer>
  )
}

// Cache Performance Chart - horizontal bar chart for L1/L2/L3
interface CachePerformanceChartProps {
  data: Array<{ layer: string; hitRate: number; color: string }>
  className?: string
  height?: number
}

export function CachePerformanceChart({ data, className, height = 200 }: CachePerformanceChartProps) {
  return (
    <ChartContainer className={className} height={height}>
      <BarChart data={data} margin={{ top: 10, right: 10, left: 0, bottom: 0 }} layout="vertical">
        <CartesianGrid strokeDasharray="3 3" stroke="#242428" horizontal={false} />
        <XAxis
          type="number"
          domain={[0, 1]}
          tickFormatter={(value) => `${(value * 100).toFixed(0)}%`}
          tick={{ fill: '#71717A', fontSize: 11, fontFamily: 'JetBrains Mono, monospace' }}
          axisLine={false}
          tickLine={false}
          dy={-10}
        />
        <YAxis
          dataKey="layer"
          type="category"
          width={100}
          tick={{ fill: '#A1A1AA', fontSize: 12, fontFamily: 'Inter, system-ui', fontWeight: 600 }}
          axisLine={false}
          tickLine={false}
        />
        <Tooltip content={<CustomTooltip />} />
        <Bar
          dataKey="hitRate"
          radius={[4, 0, 0, 4]}
          fill="#FF6B3D"
          maxBarSize={40}
        >
          {data.map((entry, index) => (
            <Bar key={index} fill={entry.color} />
          ))}
        </Bar>
      </BarChart>
    </ChartContainer>
  )
}

// Model comparison chart
interface ModelComparisonChartProps {
  data: Array<{ name: string; requests: number; cacheHitRate: number; cost: number }>
  metric: 'requests' | 'cacheHitRate' | 'cost'
  className?: string
  height?: number
}

export function ModelComparisonChart({ data, metric, className, height = 300 }: ModelComparisonChartProps) {
  const metricConfig = {
    requests: { key: 'requests', label: 'Requests', color: '#FF6B3D', format: (v: number) => v.toLocaleString() },
    cacheHitRate: { key: 'cacheHitRate', label: 'Cache Hit Rate', color: '#60A5FA', format: (v: number) => `${(v * 100).toFixed(1)}%` },
    cost: { key: 'cost', label: 'Cost ($)', color: '#22C55E', format: (v: number) => `$${v.toFixed(2)}` },
  }

  const config = metricConfig[metric]

  return (
    <ChartContainer className={className} height={height}>
      <BarChart data={data} margin={{ top: 10, right: 10, left: 0, bottom: 0 }} layout="vertical">
        <CartesianGrid strokeDasharray="3 3" stroke="#242428" horizontal={false} />
        <XAxis
          type="number"
          tickFormatter={config.format}
          tick={{ fill: '#71717A', fontSize: 11, fontFamily: 'JetBrains Mono, monospace' }}
          axisLine={false}
          tickLine={false}
          dy={-10}
        />
        <YAxis
          dataKey="name"
          type="category"
          width={160}
          tick={{ fill: '#A1A1AA', fontSize: 11, fontFamily: 'JetBrains Mono, monospace' }}
          axisLine={false}
          tickLine={false}
        />
        <Tooltip
          content={<CustomTooltip />}
          formatter={(value: number) => [config.format(value), config.label]}
        />
        <Bar
          dataKey={config.key}
          fill={config.color}
          radius={[0, 4, 4, 0]}
          maxBarSize={32}
        />
      </BarChart>
    </ChartContainer>
  )
}

// Mini sparkline chart for inline use
interface SparklineProps {
  data: TimeSeriesPoint[]
  color?: string
  className?: string
}

export function Sparkline({ data, color = '#FF6B3D', className }: SparklineProps) {
  const points = data.map((d, i) => `${(i / (data.length - 1)) * 100}%,${(1 - d.value / Math.max(...data.map(d => d.value), 1)) * 100}%`).join(' ')

  return (
    <svg className={cn('w-full h-12', className)} viewBox="0 0 100 100" preserveAspectRatio="none">
      <defs>
        <linearGradient id="sparkline-gradient" x1="0" y1="0" x2="0" y2="1">
          <stop offset="0%" stopColor={color} stopOpacity={0.3} />
          <stop offset="100%" stopColor={color} stopOpacity={0} />
        </linearGradient>
      </defs>
      <polygon
        points={`0,100 ${points} 100,100`}
        fill="url(#sparkline-gradient)"
      />
      <polyline
        points={points}
        fill="none"
        stroke={color}
        strokeWidth="1.5"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
    </svg>
  )
}