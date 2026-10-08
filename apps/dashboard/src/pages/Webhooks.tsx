// Webhooks Page

import React, { useState } from 'react'
import {
  Webhook,
  Plus,
  Edit,
  Trash2,
  Copy,
  Eye,
  ToggleLeft,
  ToggleRight,
  Send,
  CheckCircle,
  AlertCircle,
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
  CardHeader,
  Divider,
  Switch,
  Select,
  EmptyState,
} from '@/components/common'

const MOCK_WEBHOOKS = [
  {
    id: 'wh-1',
    name: 'Production Alerts',
    url: 'https://api.company.com/webhooks/cache-events',
    events: ['cache.miss', 'cache.error', 'cost.threshold'],
    secret: 'whsec_prod_abc123def456',
    enabled: true,
    created: '2024-01-15',
    lastTriggered: '2024-01-20T14:32:00Z',
    successRate: 0.998,
    totalDeliveries: 45231,
    failedDeliveries: 89,
  },
  {
    id: 'wh-2',
    name: 'Slack Notifications',
    url: 'https://notifications.company.com/webhooks/slack',
    events: ['cache.miss', 'model.switched'],
    secret: 'whsec_slack_xyz789',
    enabled: true,
    created: '2024-02-01',
    lastTriggered: '2024-01-20T14:30:00Z',
    successRate: 1.0,
    totalDeliveries: 1234,
    failedDeliveries: 0,
  },
  {
    id: 'wh-3',
    name: 'Data Pipeline',
    url: 'https://data.company.com/ingest/webhook',
    events: ['cache.hit', 'cache.miss', 'cache.invalidated', 'cost.threshold'],
    secret: 'whsec_data_pipeline_456',
    enabled: false,
    created: '2024-03-10',
    lastTriggered: '2024-01-15T10:00:00Z',
    successRate: 0.95,
    totalDeliveries: 8921,
    failedDeliveries: 446,
  },
  {
    id: 'wh-4',
    name: 'Monitoring Dashboard',
    url: 'https://monitor.company.com/webhooks/synapse',
    events: ['*'],
    secret: 'whsec_monitor_all_789',
    enabled: true,
    created: '2024-01-20',
    lastTriggered: '2024-01-20T14:31:00Z',
    successRate: 0.999,
    totalDeliveries: 156789,
    failedDeliveries: 156,
  },
]

const AVAILABLE_EVENTS = [
  { value: 'cache.hit', label: 'Cache Hit', description: 'Successful cache retrieval' },
  { value: 'cache.miss', label: 'Cache Miss', description: 'Cache lookup returned no match' },
  { value: 'cache.error', label: 'Cache Error', description: 'Cache layer encountered an error' },
  { value: 'cache.invalidated', label: 'Cache Invalidated', description: 'Cache entry was invalidated' },
  { value: 'model.switched', label: 'Model Switched', description: 'Request routed to different model' },
  { value: 'cost.threshold', label: 'Cost Threshold', description: 'Cost exceeded configured threshold' },
  { value: 'latency.threshold', label: 'Latency Threshold', description: 'Latency exceeded configured threshold' },
  { value: 'rate.limit', label: 'Rate Limit Hit', description: 'Rate limit was exceeded' },
  { value: 'tenant.quota', label: 'Tenant Quota', description: 'Tenant quota exceeded' },
]

export function Webhooks() {
  const [showCreateModal, setShowCreateModal] = useState(false)
  const [editingWebhook, setEditingWebhook] = useState<typeof MOCK_WEBHOOKS[0] | null>(null)
  const [showPayloadModal, setShowPayloadModal] = useState<typeof MOCK_WEBHOOKS[0] | null>(null)
  const [testLoading, setTestLoading] = useState<string | null>(null)

  const [formData, setFormData] = useState({
    name: '',
    url: '',
    events: [] as string[],
    secret: '',
    enabled: true,
  })

  const handleSubmit = () => {
    if (editingWebhook) {
      // Update existing
    } else {
      // Create new
    }
    setShowCreateModal(false)
    resetForm()
  }

  const resetForm = () => {
    setFormData({ name: '', url: '', events: [], secret: '', enabled: true })
    setEditingWebhook(null)
  }

  const handleEdit = (webhook: typeof MOCK_WEBHOOKS[0]) => {
    setEditingWebhook(webhook)
    setFormData({
      name: webhook.name,
      url: webhook.url,
      events: webhook.events,
      secret: webhook.secret,
      enabled: webhook.enabled,
    })
    setShowCreateModal(true)
  }

  const handleDelete = (id: string) => {
    if (confirm('Are you sure you want to delete this webhook?')) {
      // Delete
    }
  }

  const handleTest = async (webhook: typeof MOCK_WEBHOOKS[0]) => {
    setTestLoading(webhook.id)
    await new Promise(r => setTimeout(r, 1500))
    setTestLoading(null)
    alert(`Test payload sent to ${webhook.url}`)
  }

  const handleShowPayload = (webhook: typeof MOCK_WEBHOOKS[0]) => {
    setShowPayloadModal(webhook)
  }

  const maskSecret = (secret: string) => secret.slice(0, 8) + '••••••••' + secret.slice(-4)

  const getStatusBadge = (enabled: boolean, successRate: number) => {
    if (!enabled) return <Badge variant="neutral">Disabled</Badge>
    if (successRate >= 0.99) return <Badge variant="success" dot>Healthy</Badge>
    if (successRate >= 0.95) return <Badge variant="warning" dot>Degraded</Badge>
    return <Badge variant="error" dot>Failing</Badge>
  }

  return (
    <div className="space-y-6">
      {/* Page Header */}
      <div className="page-header">
        <div>
          <h1 className="page-title flex items-center gap-2">
            <Webhook className="w-6 h-6" />
            Webhooks
          </h1>
          <p className="page-description">Configure real-time event notifications for cache activity</p>
        </div>
        <Button onClick={() => { resetForm(); setShowCreateModal(true) }}>
          <Plus className="w-4 h-4 mr-2" />
          Create Webhook
        </Button>
      </div>

      {/* Webhooks List */}
      <div className="space-y-4">
        {MOCK_WEBHOOKS.map((webhook) => (
          <Card key={webhook.id} className="p-4">
            <div className="flex items-start justify-between">
              <div className="flex items-center gap-4 flex-1">
                <div className="w-12 h-12 rounded-lg bg-accent/10 flex items-center justify-center">
                  <Webhook className="w-6 h-6 text-accent" />
                </div>
                <div>
                  <div className="flex items-center gap-2">
                    <h3 className="font-medium">{webhook.name}</h3>
                    {getStatusBadge(webhook.enabled, webhook.successRate)}
                  </div>
                  <p className="text-metadata text-text-muted mt-1 truncate max-w-md">
                    {webhook.url}
                  </p>
                  <div className="flex items-center gap-4 mt-2 text-metadata">
                    <span className="flex items-center gap-1">
                      <CheckCircle className="w-3 h-3 text-success" />
                      {webhook.totalDeliveries.toLocaleString()} delivered
                    </span>
                    <span className="flex items-center gap-1">
                      {webhook.failedDeliveries > 0 ? (
                        <>
                          <AlertCircle className="w-3 h-3 text-error" />
                          {webhook.failedDeliveries.toLocaleString()} failed
                        </>
                      ) : (
                        <>
                          <CheckCircle className="w-3 h-3 text-success" />
                          0 failed
                        </>
                      )}
                    </span>
                    <span className="flex items-center gap-1">
                      <Loader2 className="w-3 h-3 text-text-muted" />
                      Last: {formatRelativeTime(webhook.lastTriggered)}
                    </span>
                  </div>
                  <div className="flex flex-wrap gap-1 mt-2">
                    {webhook.events.map(event => {
                      const eventInfo = AVAILABLE_EVENTS.find(e => e.value === event)
                      return (
                        <Badge key={event} variant="outline" className="text-xs">
                          {eventInfo?.label || event}
                        </Badge>
                      )
                    })}
                    {webhook.events.includes('*') && <Badge key="all" variant="info" className="text-xs">All Events</Badge>}
                  </div>
                </div>
              </div>

              <div className="flex items-center gap-2">
                <Switch
                  checked={webhook.enabled}
                  onChange={(checked) => {}}
                />
                <div className="relative">
                  <code className="code mr-2">{maskSecret(webhook.secret)}</code>
                  <Button variant="ghost" size="sm" onClick={() => handleShowPayload(webhook)}>
                    <Eye className="w-4 h-4" />
                  </Button>
                </div>
                <Button variant="ghost" size="sm" onClick={() => handleTest(webhook)} disabled={testLoading === webhook.id}>
                  {testLoading === webhook.id ? <Loader2 className="w-4 h-4 animate-spin" /> : <Send className="w-4 h-4" />}
                </Button>
                <Button variant="ghost" size="sm" onClick={() => handleEdit(webhook)}>
                  <Edit className="w-4 h-4" />
                </Button>
                <Button variant="ghost" size="sm" onClick={() => handleDelete(webhook.id)}>
                  <Trash2 className="w-4 h-4" />
                </Button>
              </div>
            </div>
          </Card>
        ))}
      </div>

      {/* Create/Edit Modal */}
      {(showCreateModal || editingWebhook) && (
        <div className="fixed inset-0 z-50 flex items-center justify-center p-4">
          <div className="absolute inset-0 bg-black/50" onClick={() => { setShowCreateModal(false); resetForm() }} />
          <Card className="w-full max-w-2xl max-h-[90vh] overflow-y-auto">
            <CardHeader className="flex items-center justify-between">
              <h3 className="text-section-title">{editingWebhook ? 'Edit Webhook' : 'Create Webhook'}</h3>
              <Button variant="ghost" size="sm" onClick={() => { setShowCreateModal(false); resetForm() }}>
                <XCircle className="w-4 h-4" />
              </Button>
            </CardHeader>
            <CardContent className="space-y-4 pb-6">
              <Input
                label="Webhook Name"
                value={formData.name}
                onChange={(e) => setFormData({ ...formData, name: e.target.value })}
                placeholder="e.g., Production Alerts"
              />
              <Input
                label="URL"
                type="url"
                value={formData.url}
                onChange={(e) => setFormData({ ...formData, url: e.target.value })}
                placeholder="https://your-endpoint.com/webhook"
              />
              <div className="space-y-2">
                <label className="text-metadata text-text-muted">Events to Subscribe</label>
                <div className="grid grid-cols-1 sm:grid-cols-2 gap-2 max-h-60 overflow-y-auto p-2 border border-border-subtle rounded">
                  {AVAILABLE_EVENTS.map(event => (
                    <label key={event.value} className="flex items-center gap-2 cursor-pointer p-2 hover:bg-bg-elevated rounded">
                      <input
                        type="checkbox"
                        checked={formData.events.includes(event.value)}
                        onChange={(e) => setFormData({
                          ...formData,
                          events: e.target.checked
                            ? [...formData.events, event.value]
                            : formData.events.filter(v => v !== event.value)
                        })}
                        className="rounded border-border-subtle text-accent focus:ring-accent"
                      />
                      <div>
                        <span className="font-medium text-body">{event.label}</span>
                        <p className="text-caption text-text-muted">{event.description}</p>
                      </div>
                    </label>
                  ))}
                  <label className="flex items-center gap-2 cursor-pointer p-2 hover:bg-bg-elevated rounded">
                    <input
                      type="checkbox"
                      checked={formData.events.includes('*')}
                      onChange={(e) => setFormData({
                        ...formData,
                        events: e.target.checked ? ['*'] : []
                      })}
                      className="rounded border-border-subtle text-accent focus:ring-accent"
                    />
                    <div>
                      <span className="font-medium text-body">All Events</span>
                      <p className="text-caption text-text-muted">Subscribe to all event types</p>
                    </div>
                  </label>
                </div>
              </div>
              <Input
                label="Signing Secret (optional)"
                value={formData.secret}
                onChange={(e) => setFormData({ ...formData, secret: e.target.value })}
                placeholder="Leave empty to auto-generate"
                helperText="Used to verify webhook signatures. Auto-generated if empty."
              />
              <Switch
                label="Enabled"
                checked={formData.enabled}
                onChange={(checked) => setFormData({ ...formData, enabled: checked })}
              />
              <Divider />
              <div className="flex justify-end gap-2">
                <Button variant="secondary" onClick={() => { setShowCreateModal(false); resetForm() }}>Cancel</Button>
                <Button onClick={handleSubmit} disabled={!formData.name.trim() || !formData.url.trim() || formData.events.length === 0}>
                  {editingWebhook ? 'Save Changes' : 'Create Webhook'}
                </Button>
              </div>
            </CardContent>
          </Card>
        </div>
      )}

      {/* Payload Example Modal */}
      {showPayloadModal && (
        <div className="fixed inset-0 z-50 flex items-center justify-center p-4">
          <div className="absolute inset-0 bg-black/50" onClick={() => setShowPayloadModal(null)} />
          <Card className="w-full max-w-3xl max-h-[90vh] overflow-y-auto">
            <CardHeader className="flex items-center justify-between">
              <h3 className="text-section-title">Example Payload</h3>
              <Button variant="ghost" size="sm" onClick={() => setShowPayloadModal(null)}>
                <XCircle className="w-4 h-4" />
              </Button>
            </CardHeader>
            <CardContent className="p-4">
              <pre className="code overflow-x-auto text-sm max-h-[60vh] overflow-y-auto">
{JSON.stringify({
  id: 'evt_abc123',
  type: 'cache.miss',
  timestamp: new Date().toISOString(),
  tenant: 'default',
  data: {
    requestId: 'req_xyz789',
    model: 'gpt-4o',
    prompt: 'What is the capital of France?',
    cacheKey: 'sha256:abc123...',
    layer: 'L2',
    similarity: 0.72,
  },
  signature: 'sha256=abc123...'
}, null, 2)}
              </pre>
              <div className="flex justify-end gap-2 mt-4">
                <Button variant="secondary" onClick={() => setShowPayloadModal(null)}>Close</Button>
                <Button onClick={() => navigator.clipboard.writeText(JSON.stringify({
                  id: 'evt_abc123',
                  type: 'cache.miss',
                  timestamp: new Date().toISOString(),
                  tenant: 'default',
                  data: {
                    requestId: 'req_xyz789',
                    model: 'gpt-4o',
                    prompt: 'What is the capital of France?',
                    cacheKey: 'sha256:abc123...',
                    layer: 'L2',
                    similarity: 0.72,
                  },
                  signature: 'sha256=abc123...'
                }, null, 2))}>
                  <Copy className="w-4 h-4 mr-1" />
                  Copy JSON
                </Button>
              </div>
            </CardContent>
          </Card>
        </div>
      )}
    </div>
  )
}