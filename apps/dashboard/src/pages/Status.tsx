// Status Page

import React from 'react'
import {
  CheckCircle,
  AlertTriangle,
  XCircle,
  Loader2,
  Server,
  Database,
  Zap,
  Network,
  RefreshCw,
  Calendar,
  Clock,
  TrendingUp,
  TrendingDown,
  Minus,
} from 'lucide-react'
import { cn } from '@/components/common'
import { formatRelativeTime, formatDuration, formatPercent } from '@/lib/formatters'
import {
  Button,
  Badge,
  Card,
  CardContent,
  Progress,
  Divider,
} from '@/components/common'

const SERVICES = [
  { id: 'api', name: 'Cache API', type: 'core', status: 'operational', uptime: 99.99, latency: 12, lastIncident: '2024-01-10', description: 'Main API gateway for cache operations' },
  { id: 'embedding', name: 'Embedding Worker', type: 'core', status: 'operational', uptime: 99.95, latency: 234, lastIncident: '2024-01-15', description: 'Generates vector embeddings for L2 cache' },
  { id: 'invalidation', name: 'Invalidation Service', type: 'core', status: 'operational', uptime: 99.98, latency: 45, lastIncident: '2024-01-05', description: 'Handles cache invalidation across layers' },
  { id: 'qdrant', name: 'Vector Store (Qdrant)', type: 'dependency', status: 'operational', uptime: 99.99, latency: 8, lastIncident: '2024-01-01', description: 'Vector database for semantic search' },
  { id: 'redis', name: 'Cache Store (Redis)', type: 'dependency', status: 'operational', uptime: 99.99, latency: 2, lastIncident: '2024-01-01', description: 'In-memory cache for L1 exact matches' },
  { id: 'rate-limiter', name: 'Rate Limiter', type: 'core', status: 'operational', uptime: 100, latency: 1, lastIncident: 'Never', description: 'Token bucket rate limiting' },
  { id: 'cost-tracker', name: 'Cost Tracker', type: 'core', status: 'operational', uptime: 100, latency: 5, lastIncident: 'Never', description: 'Tracks token usage and costs' },
  { id: 'health', name: 'Health Check', type: 'core', status: 'operational', uptime: 100, latency: 1, lastIncident: 'Never', description: 'System health monitoring' },
]

const INCIDENTS = [
  { id: 'inc-1', title: 'Elevated L2 Latency', status: 'resolved', severity: 'minor', start: '2024-01-15T10:30:00Z', end: '2024-01-15T11:45:00Z', affected: ['Embedding Worker', 'Vector Store'], description: 'Vector store experienced elevated latency due to index optimization.' },
  { id: 'inc-2', title: 'Cache API Partial Outage', status: 'resolved', severity: 'major', start: '2024-01-10T14:00:00Z', end: '2024-01-10T14:23:00Z', affected: ['Cache API', 'Rate Limiter'], description: 'Rate limiter misconfiguration caused request drops.' },
  { id: 'inc-3', title: 'Scheduled Maintenance', status: 'scheduled', severity: 'maintenance', start: '2024-01-25T02:00:00Z', end: '2024-01-25T04:00:00Z', affected: ['All Services'], description: 'Planned infrastructure upgrade. Expect brief interruptions.' },
  { id: 'inc-4', title: 'Vector Store Degraded Performance', status: 'resolved', severity: 'minor', start: '2024-01-05T09:15:00Z', end: '2024-01-05T10:30:00Z', affected: ['Vector Store', 'Embedding Worker'], description: 'Disk I/O contention during backup window.' },
]

const getStatusIcon = (status: string) => {
  switch (status) {
    case 'operational': return <CheckCircle className="w-4 h-4 text-success" />
    case 'degraded': return <AlertTriangle className="w-4 h-4 text-warning" />
    case 'outage': return <XCircle className="w-4 h-4 text-error" />
    case 'maintenance': return <Loader2 className="w-4 h-4 text-info animate-spin" />
    default: return <Minus className="w-4 h-4 text-text-muted" />
  }
}

const getIncidentStatusBadge = (status: string) => {
  switch (status) {
    case 'resolved': return <Badge variant="success" dot>Resolved</Badge>
    case 'investigating': return <Badge variant="warning" dot>Investigating</Badge>
    case 'identified': return <Badge variant="info" dot>Identified</Badge>
    case 'monitoring': return <Badge variant="info" dot>Monitoring</Badge>
    case 'scheduled': return <Badge variant="neutral" dot>Scheduled</Badge>
    default: return <Badge variant="neutral">{status}</Badge>
  }
}

const getSeverityBadge = (severity: string) => {
  switch (severity) {
    case 'critical': return <Badge variant="error">{severity}</Badge>
    case 'major': return <Badge variant="error">{severity}</Badge>
    case 'minor': return <Badge variant="warning">{severity}</Badge>
    case 'maintenance': return <Badge variant="info">{severity}</Badge>
    default: return <Badge variant="neutral">{severity}</Badge>
  }
}

export function Status() {
  const overallStatus = SERVICES.every(s => s.status === 'operational') ? 'operational' : 
    SERVICES.some(s => s.status === 'outage') ? 'outage' : 'degraded'

  return (
    <div className="space-y-6">
      {/* Page Header */}
      <div className="page-header">
        <div>
          <h1 className="page-title flex items-center gap-2">
            <Server className="w-6 h-6" />
            System Status
          </h1>
          <p className="page-description">Real-time service health and incident history</p>
        </div>
        <div className="flex items-center gap-4">
          <div className="flex items-center gap-2 px-3 py-1 rounded-lg bg-bg-elevated border border-border-subtle">
            {getStatusIcon(overallStatus)}
            <span className="font-medium capitalize">{overallStatus}</span>
          </div>
          <Button variant="secondary" size="sm" onClick={() => window.location.reload()}>
            <RefreshCw className="w-4 h-4" />
            Refresh
          </Button>
        </div>
      </div>

      {/* Overall Status */}
      <Card className="border-accent/30 bg-accent/5">
        <CardContent className="pt-4">
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-3">
              <div className="w-16 h-16 rounded-xl bg-accent/10 flex items-center justify-center">
                {getStatusIcon(overallStatus)}
              </div>
              <div>
                <h3 className="text-section-title">All Systems Operational</h3>
                <p className="text-body text-text-secondary">No active incidents. All services running normally.</p>
              </div>
            </div>
            <div className="text-right">
              <p className="text-metadata text-text-muted">Last Updated</p>
              <p className="font-mono tabular-nums">{formatRelativeTime(new Date().toISOString())}</p>
            </div>
          </div>
        </CardContent>
      </Card>

      {/* Services Grid */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
        {['core', 'dependency'].map(category => (
          <Card key={category}>
            <CardContent className="pt-4">
              <h3 className="font-medium text-text-secondary mb-4 capitalize">{category} Services</h3>
              <div className="space-y-3">
                {SERVICES.filter(s => s.type === category).map(service => (
                  <div key={service.id} className="p-3 rounded-lg border border-border-subtle hover:bg-bg-elevated/50 transition-colors">
                    <div className="flex items-center justify-between">
                      <div className="flex items-center gap-3">
                        <div className="w-10 h-10 rounded-lg bg-accent/10 flex items-center justify-center">
                          {service.type === 'core' ? <Zap className="w-5 h-5 text-accent" /> : <Database className="w-5 h-5 text-accent" />}
                        </div>
                        <div>
                          <div className="flex items-center gap-2">
                            <h4 className="font-medium">{service.name}</h4>
                            {getStatusIcon(service.status)}
                          </div>
                          <p className="text-caption text-text-muted">{service.description}</p>
                        </div>
                      </div>
                      <div className="text-right">
                        <div className="flex items-center justify-end gap-2 text-metadata">
                          <span className="flex items-center gap-1">
                            <Clock className="w-3 h-3" />
                            {formatDuration(service.latency)}
                          </span>
                          <span className="flex items-center gap-1">
                            <TrendingUp className="w-3 h-3 text-success" />
                            {service.uptime}%
                          </span>
                        </div>
                        <p className="text-caption text-text-muted">Last incident: {service.lastIncident}</p>
                      </div>
                    </div>
                  </div>
                ))}
              </div>
            </CardContent>
          </Card>
        ))}
      </div>

      {/* Incident History */}
      <Card>
        <CardContent className="pt-4">
          <div className="flex items-center justify-between mb-4">
            <h3 className="font-medium">Incident History</h3>
            <Badge variant="outline">{INCIDENTS.length} incidents (30 days)</Badge>
          </div>
          <div className="space-y-3">
            {INCIDENTS.map(incident => (
              <div key={incident.id} className="p-4 rounded-lg border border-border-subtle">
                <div className="flex items-start justify-between gap-4">
                  <div className="flex-1">
                    <div className="flex items-center gap-2 mb-2">
                      <h4 className="font-medium">{incident.title}</h4>
                      {getIncidentStatusBadge(incident.status)}
                      {getSeverityBadge(incident.severity)}
                    </div>
                    <p className="text-body text-text-secondary mb-2">{incident.description}</p>
                    <div className="flex flex-wrap items-center gap-4 text-metadata">
                      <span className="flex items-center gap-1">
                        <Calendar className="w-3 h-3" />
                        {new Date(incident.start).toLocaleDateString()} {new Date(incident.start).toLocaleTimeString()}
                        {incident.end && <span>\u2013 {new Date(incident.end).toLocaleTimeString()}</span>}
                      </span>
                      <span className="flex items-center gap-1">
                        <Server className="w-3 h-3" />
                        {incident.affected.join(', ')}
                      </span>
                    </div>
                  </div>
                  <Button variant="ghost" size="sm">View Details</Button>
                </div>
              </div>
            ))}
          </div>
        </CardContent>
      </Card>

      {/* Uptime Summary */}
      <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
        <Card>
          <CardContent className="pt-4">
            <div className="flex items-center justify-between">
              <div>
                <p className="text-metadata text-text-muted">30-DAY UPTIME</p>
                <p className="text-3xl font-semibold font-mono tabular-nums text-success">99.99%</p>
              </div>
              <CheckCircle className="w-10 h-10 text-success/30" />
            </div>
            <Progress value={99.99} className="mt-4 h-1" max={100} />
            <p className="text-caption text-text-muted mt-2">Target: 99.9%</p>
          </CardContent>
        </Card>
        <Card>
          <CardContent className="pt-4">
            <div className="flex items-center justify-between">
              <div>
                <p className="text-metadata text-text-muted">AVG LATENCY (P95)</p>
                <p className="text-3xl font-semibold font-mono tabular-nums">{formatDuration(45)}</p>
              </div>
              <Zap className="w-10 h-10 text-accent/30" />
            </div>
            <Progress value={90} className="mt-4 h-1" max={100} />
            <p className="text-caption text-text-muted mt-2">{"Target: < 100ms"}</p>
          </CardContent>
        </Card>
        <Card>
          <CardContent className="pt-4">
            <div className="flex items-center justify-between">
              <div>
                <p className="text-metadata text-text-muted">ERROR RATE</p>
                <p className="text-3xl font-semibold font-mono tabular-nums text-success">{formatPercent(0.001)}</p>
              </div>
              <XCircle className="w-10 h-10 text-error/30" />
            </div>
            <Progress value={0.1} className="mt-4 h-1" max={1} />
            <p className="text-caption text-text-muted mt-2">{"Target: < 0.1%"}</p>
          </CardContent>
        </Card>
      </div>
    </div>
  )
}