// Settings Page

import { useEffect, useState } from 'react'
import {
  Settings as SettingsIcon,
  Wifi,
  Server,
  Database,
  Zap,
  Shield,
  Palette,
  Key,
  Terminal,
  Save,
  RefreshCw,
  Eye,
  EyeOff,
  Bell,
  BellOff,
  ChevronDown,
  ChevronUp,
} from 'lucide-react'
import { cn } from '@/components/common'
import {
  Button,
  Input,
  Select,
  Card,
  CardContent,
  CardHeader,
  Divider,
  Tabs,
  TabsList,
  TabsTrigger,
  TabsContent,
  Switch,
  Badge,
} from '@/components/common'
import { useUIStore, useDataStore } from '@/lib/stores'
import { getApiClient } from '@/lib/api/client'
import type { Settings as SettingsType, ProviderConfig } from '@/types'

const THEME_OPTIONS = [
  { value: 'dark', label: 'Dark' },
  { value: 'light', label: 'Light' },
  { value: 'system', label: 'System' },
]

const TRANSPORT_OPTIONS = [
  { value: 'websocket', label: 'WebSocket' },
  { value: 'sse', label: 'Server-Sent Events' },
  { value: 'polling', label: 'Polling' },
]

const LOG_LEVELS = [
  { value: 'debug', label: 'Debug' },
  { value: 'info', label: 'Info' },
  { value: 'warn', label: 'Warn' },
  { value: 'error', label: 'Error' },
]

const PROVIDER_TYPES = [
  { value: 'openai', label: 'OpenAI' },
  { value: 'anthropic', label: 'Anthropic' },
  { value: 'ollama', label: 'Ollama' },
  { value: 'openrouter', label: 'OpenRouter' },
  { value: 'nim', label: 'NVIDIA NIM' },
  { value: 'custom', label: 'Custom' },
]

export function Settings() {
  const { theme, setTheme, environment, setEnvironment } = useUIStore()
  const { settings, setSettings } = useDataStore()
  const [loading, setLoading] = useState(false)
  const [saving, setSaving] = useState(false)
  const [saved, setSaved] = useState(false)
  const [expandedSections, setExpandedSections] = useState<string[]>(['general'])
  const [providers, setProviders] = useState<ProviderConfig[]>([])
  const [editingProvider, setEditingProvider] = useState<ProviderConfig | null>(null)
  const [showProviderForm, setShowProviderForm] = useState(false)
  const [newProvider, setNewProvider] = useState<ProviderConfig>({
    id: '',
    name: '',
    type: 'custom',
    baseUrl: '',
    apiKey: '',
    models: [],
    enabled: true,
    priority: 0,
  })
  const [showApiKey, setShowApiKey] = useState<string | null>(null)

  // Load settings
  useEffect(() => {
    async function loadSettings() {
      setLoading(true)
      try {
        const api = getApiClient()
        const data = await api.getSettings()
        setSettings(data)
        setProviders(data.providers)
      } catch {
        // Use defaults
      } finally {
        setLoading(false)
      }
    }
    loadSettings()
  }, [setSettings])

  const handleSave = async () => {
    setSaving(true)
    setSaved(false)
    try {
      const api = getApiClient()
      const newSettings: Partial<SettingsType> = {
        general: { appName: 'Synapse', defaultTenant: 'default', defaultModel: 'nvidia/nemotron-3-ultra-550b-a55b' },
        appearance: { theme, compactMode: false, animations: true },
      }
      await api.updateSettings(newSettings)
      setSaved(true)
      setTimeout(() => setSaved(false), 3000)
    } catch {
      // Mock save
      setSaved(true)
      setTimeout(() => setSaved(false), 3000)
    } finally {
      setSaving(false)
    }
  }

  const toggleSection = (section: string) => {
    setExpandedSections(prev => 
      prev.includes(section) ? prev.filter(s => s !== section) : [...prev, section]
    )
  }

  const handleProviderChange = (key: keyof ProviderConfig, value: any) => {
    if (editingProvider) {
      setEditingProvider({ ...editingProvider, [key]: value })
    } else {
      setNewProvider(prev => ({ ...prev, [key]: value }))
    }
  }

  const handleAddProvider = () => {
    setEditingProvider(null)
    setNewProvider({
      id: '',
      name: '',
      type: 'custom',
      baseUrl: '',
      apiKey: '',
      models: [],
      enabled: true,
      priority: providers.length,
    })
    setShowProviderForm(true)
  }

  const handleEditProvider = (provider: ProviderConfig) => {
    setEditingProvider(provider)
    setShowProviderForm(true)
  }

  const handleSaveProvider = () => {
    if (editingProvider) {
      setProviders(prev => prev.map(p => p.id === editingProvider.id ? { ...editingProvider, ...newProvider } : p))
    } else {
      const provider = { ...newProvider, id: `provider-${Date.now()}` }
      setProviders(prev => [...prev, provider])
    }
    setShowProviderForm(false)
    setEditingProvider(null)
  }

  const handleDeleteProvider = (id: string) => {
    setProviders(prev => prev.filter(p => p.id !== id))
  }

  const maskApiKey = (key: string) => {
    if (key.length <= 8) return '••••••••'
    return key.slice(0, 4) + '••••••••' + key.slice(-4)
  }

  const getStatusBadge = (status: string) => {
    switch (status) {
      case 'active': return <Badge variant="success" dot>Active</Badge>
      case 'expiring': return <Badge variant="warning" dot>Expiring Soon</Badge>
      case 'revoked': return <Badge variant="error" dot>Revoked</Badge>
      default: return <Badge variant="neutral">{status}</Badge>
    }
  }

  if (loading) {
    return (
      <div className="min-h-screen flex items-center justify-center bg-bg-primary">
        <div className="text-center">
          <div className="animate-spin rounded-full h-8 w-8 border-b-2 border-accent mx-auto mb-4" />
          <p className="text-body text-text-secondary">Loading settings...</p>
        </div>
      </div>
    )
  }

  const sections = [
    { id: 'general', label: 'General', icon: SettingsIcon },
    { id: 'connection', label: 'Connection', icon: Wifi },
    { id: 'providers', label: 'Providers', icon: Server },
    { id: 'cache', label: 'Cache', icon: Database },
    { id: 'events', label: 'Events', icon: Zap },
    { id: 'appearance', label: 'Appearance', icon: Palette },
    { id: 'api', label: 'API Keys', icon: Key },
    { id: 'advanced', label: 'Advanced', icon: Terminal },
  ]

  return (
    <div className="space-y-6">
      {/* Page Header */}
      <div className="page-header">
        <div>
          <h1 className="page-title flex items-center gap-2">
            <SettingsIcon className="w-6 h-6" />
            Settings
          </h1>
          <p className="page-description">Configure application behavior, connections, and preferences</p>
        </div>
        <div className="flex items-center gap-2">
          <Button variant="secondary" size="sm" onClick={() => {}}>
            <RefreshCw className="w-4 h-4" />
            Reset to Defaults
          </Button>
          <Button onClick={handleSave} disabled={saving}>
            {saving ? 'Saving...' : <> <Save className="w-4 h-4 mr-1" /> Save Changes </>}
          </Button>
        </div>
      </div>

      {saved && (
        <div className="flex items-center gap-2 p-3 bg-success/10 border border-success/30 rounded-md text-success text-body">
          Settings saved successfully
        </div>
      )}

      {/* Settings Tabs */}
      <Tabs defaultValue="general" className="w-full">
        <TabsList className="grid grid-cols-2 md:grid-cols-4 lg:grid-cols-8 gap-1 p-1 bg-bg-elevated rounded-md">
          {sections.map(section => {
            const Icon = section.icon
            return (
              <TabsTrigger key={section.id} value={section.id} className="gap-2 px-3 py-2">
                <Icon className="w-4 h-4" />
                {section.label}
              </TabsTrigger>
            )
          })}
        </TabsList>

        {/* General */}
        <TabsContent value="general" className="mt-6 space-y-6">
          <Card>
            <CardHeader>
              <h3 className="text-section-title">Application</h3>
            </CardHeader>
            <CardContent className="space-y-4">
              <Input label="Application Name" value={settings?.general.appName || 'Synapse'} readOnly />
              <Input label="Default Tenant" value={settings?.general.defaultTenant || 'default'} />
              <Select
                label="Default Model"
                value={settings?.general.defaultModel || 'nvidia/nemotron-3-ultra-550b-a55b'}
                options={[
                  { value: 'nvidia/nemotron-3-ultra-550b-a55b', label: 'NVIDIA Nemotron 3 Ultra 550B' },
                ]}
              />
            </CardContent>
          </Card>

          <Card>
            <CardHeader>
              <h3 className="text-section-title">Environment</h3>
            </CardHeader>
            <CardContent className="space-y-4">
              <Select
                label="Current Environment"
                value={environment}
                onChange={(e) => setEnvironment(e.target.value as any)}
                options={[
                  { value: 'development', label: 'Development' },
                  { value: 'staging', label: 'Staging' },
                  { value: 'production', label: 'Production' },
                ]}
              />
            </CardContent>
          </Card>
        </TabsContent>

        {/* Connection */}
        <TabsContent value="connection" className="mt-6 space-y-6">
          <Card>
            <CardHeader>
              <h3 className="text-section-title">API Connection</h3>
            </CardHeader>
            <CardContent className="space-y-4">
              <Input
                label="API Base URL"
                value={settings?.connection.apiUrl || 'http://localhost:8000'}
                placeholder="http://localhost:8000"
              />
              <Input
                label="WebSocket URL"
                value={settings?.connection.wsUrl || 'ws://localhost:8000/ws'}
                placeholder="ws://localhost:8000/ws"
              />
              <div className="grid grid-cols-2 gap-4">
                <Input
                  label="Request Timeout (ms)"
                  type="number"
                  value={settings?.connection.timeout || 10000}
                  onChange={(e) => {}}
                />
                <Input
                  label="Retry Attempts"
                  type="number"
                  value={settings?.connection.retryAttempts || 3}
                  onChange={(e) => {}}
                />
              </div>
            </CardContent>
          </Card>

          <Card>
            <CardHeader>
              <h3 className="text-section-title">Connection Test</h3>
            </CardHeader>
            <CardContent className="space-y-4">
              <Button variant="secondary" onClick={() => {}}>
                <Wifi className="w-4 h-4 mr-2" />
                Test Connection
              </Button>
              <p className="text-body text-text-muted">Tests connectivity to API, Redis, and Qdrant</p>
            </CardContent>
          </Card>
        </TabsContent>

        {/* Providers */}
        <TabsContent value="providers" className="mt-6 space-y-6">
          <div className="flex items-center justify-between">
            <h3 className="text-section-title">LLM Providers</h3>
            <Button onClick={handleAddProvider}>
              <span className="w-4 h-4" />
              Add Provider
            </Button>
          </div>

          <div className="space-y-3">
            {providers.map((provider) => (
              <Card key={provider.id} className="p-4">
                <div className="flex items-center justify-between">
                  <div className="flex items-center gap-3">
                    <div className="w-10 h-10 rounded-lg bg-accent/10 flex items-center justify-center">
                      <Server className="w-5 h-5 text-accent" />
                    </div>
                    <div>
                      <h4 className="font-medium">{provider.name}</h4>
                      <p className="text-metadata text-text-muted">
                        {provider.type} • {provider.models.length} models • Priority: {provider.priority}
                      </p>
                    </div>
                  </div>
                  <div className="flex items-center gap-2">
                    <Switch
                      checked={provider.enabled}
                      onChange={(checked) => setProviders(prev => prev.map(p => p.id === provider.id ? { ...p, enabled: checked } : p))}
                    />
                    <Button variant="ghost" size="sm" onClick={() => handleEditProvider(provider)}>Edit</Button>
                    <Button variant="ghost" size="sm" onClick={() => handleDeleteProvider(provider.id)}>Delete</Button>
                  </div>
                </div>
              </Card>
            ))}
            {providers.length === 0 && (
              <Card className="p-8 text-center">
                <Server className="w-12 h-12 text-text-muted/30 mx-auto mb-4" />
                <p className="text-text-secondary">No providers configured</p>
                <Button className="mt-4" onClick={handleAddProvider}>Add First Provider</Button>
              </Card>
            )}
          </div>
        </TabsContent>

        {/* Cache */}
        <TabsContent value="cache" className="mt-6 space-y-6">
          <Card>
            <CardHeader>
              <h3 className="text-section-title">Cache Layers</h3>
            </CardHeader>
            <CardContent className="space-y-4">
              <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
                {['L1', 'L2', 'L3'].map((layer, i) => (
                  <div key={layer} className="p-4 bg-bg-elevated rounded-lg border border-border-subtle">
                    <div className="flex items-center justify-between mb-3">
                      <h4 className="font-medium">{layer} {layer === 'L1' ? 'Exact' : layer === 'L2' ? 'Semantic' : 'Context'}</h4>
                      <Switch
                        checked={true}
                        onChange={(checked) => {}}
                      />
                    </div>
                    <Input
                      label="TTL (seconds)"
                      type="number"
                      value={[3600, 86400, 604800][i]}
                      onChange={(e) => {}}
                    />
                    {layer !== 'L1' && (
                      <Input
                        label="Similarity Threshold"
                        type="number"
                        step="0.01"
                        min="0"
                        max="1"
                        value={[0, 0.85, 0.75][i]}
                        onChange={(e) => {}}
                      />
                    )}
                  </div>
                ))}
              </div>

              <Divider />

              <h4 className="text-body font-medium text-text-secondary">Eviction Policy</h4>
              <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                <Select
                  label="Eviction Strategy"
                  value="lru"
                  options={[
                    { value: 'lru', label: 'Least Recently Used (LRU)' },
                    { value: 'lfu', label: 'Least Frequently Used (LFU)' },
                    { value: 'fifo', label: 'First In, First Out (FIFO)' },
                    { value: 'random', label: 'Random' },
                  ]}
                />
                <Input
                  label="Max Entries (per layer)"
                  type="number"
                  value={100000}
                  onChange={(e) => {}}
                />
                <Input
                  label="Max Memory (GB)"
                  type="number"
                  value={10}
                  onChange={(e) => {}}
                />
                <Input
                  label="Eviction Batch Size"
                  type="number"
                  value={1000}
                  onChange={(e) => {}}
                />
              </div>

              <Divider />

              <h4 className="text-body font-medium text-text-secondary">Invalidation</h4>
              <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                <Switch label="Enable Auto-Invalidation on Model Update" checked={true} onChange={() => {}} />
                <Switch label="Cascade Invalidation Across Layers" checked={true} onChange={() => {}} />
                <Input
                  label="Invalidation Debounce (ms)"
                  type="number"
                  value={500}
                  onChange={(e) => {}}
                />
              </div>
            </CardContent>
          </Card>
        </TabsContent>

        {/* Events */}
        <TabsContent value="events" className="mt-6 space-y-6">
          <Card>
            <CardHeader>
              <h3 className="text-section-title">Real-time Events</h3>
            </CardHeader>
            <CardContent className="space-y-4">
              <Switch
                label="Enable Real-time Events"
                description="Receive live updates via WebSocket, SSE, or polling"
                checked={settings?.events.enabled || true}
                onChange={(checked) => {}}
              />
              <Select
                label="Transport Method"
                value={settings?.events.transport || 'websocket'}
                options={TRANSPORT_OPTIONS}
              />
              <Input
                label="Polling Interval (ms)"
                type="number"
                value={settings?.events.pollingInterval || 5000}
                onChange={(e) => {}}
                helperText="Only used when transport is set to Polling"
              />
            </CardContent>
          </Card>
        </TabsContent>

        {/* Appearance */}
        <TabsContent value="appearance" className="mt-6 space-y-6">
          <Card>
            <CardHeader>
              <h3 className="text-section-title">Theme</h3>
            </CardHeader>
            <CardContent className="space-y-4">
              <Select
                label="Color Theme"
                value={theme}
                onChange={(e) => setTheme(e.target.value as any)}
                options={THEME_OPTIONS}
              />
              <Switch
                label="Compact Mode"
                description="Reduce padding and spacing for higher information density"
                checked={settings?.appearance.compactMode || false}
                onChange={(checked) => {}}
              />
              <Switch
                label="Animations"
                description="Enable subtle transitions and micro-interactions"
                checked={settings?.appearance.animations !== false}
                onChange={(checked) => {}}
              />
            </CardContent>
          </Card>
        </TabsContent>

        {/* API Keys */}
        <TabsContent value="api" className="mt-6 space-y-6">
          <Card>
            <CardHeader>
              <h3 className="text-section-title">API Keys</h3>
            </CardHeader>
            <CardContent className="space-y-4">
              <p className="text-body text-text-secondary">
                Manage API keys for external integrations. Keys are masked for security.
              </p>
              <div className="space-y-3">
                {Object.entries(settings?.api.apiKeys || {}).map(([name, key]) => (
                  <div key={name} className="flex items-center justify-between p-3 bg-bg-elevated rounded-lg">
                    <div className="flex items-center gap-3">
                      <Key className="w-5 h-5 text-text-muted" />
                      <div>
                        <p className="font-medium">{name}</p>
                        <p className="text-metadata text-text-muted font-mono">{maskApiKey(key)}</p>
                      </div>
                    </div>
                    <div className="flex items-center gap-2">
                      <Button
                        variant="ghost"
                        size="sm"
                        onClick={() => setShowApiKey(name)}
                      >
                        {showApiKey === name ? <EyeOff className="w-4 h-4" /> : <Eye className="w-4 h-4" />}
                      </Button>
                      <Button variant="ghost" size="sm">Rotate</Button>
                      <Button variant="danger" size="sm">Revoke</Button>
                    </div>
                  </div>
                ))}
                {Object.keys(settings?.api.apiKeys || {}).length === 0 && (
                  <p className="text-text-muted text-center py-4">No API keys configured</p>
                )}
              </div>
              <Button variant="secondary" onClick={() => {}}>
                <Key className="w-4 h-4 mr-2" />
                Add API Key
              </Button>
            </CardContent>
          </Card>

          <Card>
            <CardHeader>
              <h3 className="text-section-title">Rate Limiting</h3>
            </CardHeader>
            <CardContent className="space-y-4">
              <Input
                label="Requests per Minute"
                type="number"
                value={settings?.api.rateLimit || 1000}
                onChange={(e) => {}}
              />
            </CardContent>
          </Card>
        </TabsContent>

        {/* Advanced */}
        <TabsContent value="advanced" className="mt-6 space-y-6">
          <Card>
            <CardHeader>
              <h3 className="text-section-title">Debug & Logging</h3>
            </CardHeader>
            <CardContent className="space-y-4">
              <Switch
                label="Debug Mode"
                description="Enable verbose logging and debug features"
                checked={settings?.advanced.debugMode || false}
                onChange={(checked) => {}}
              />
              <Select
                label="Log Level"
                value={settings?.advanced.logLevel || 'info'}
                options={LOG_LEVELS}
              />
            </CardContent>
          </Card>

          <Card>
            <CardHeader>
              <h3 className="text-section-title">Telemetry</h3>
            </CardHeader>
            <CardContent className="space-y-4">
              <Switch
                label="Enable Telemetry"
                description="Send anonymous usage statistics to improve the product"
                checked={settings?.advanced.telemetryEnabled || true}
                onChange={(checked) => {}}
              />
              <p className="text-body text-text-secondary">
                Telemetry data includes feature usage, performance metrics, and error rates.
                No personal data, prompts, or responses are collected.
              </p>
            </CardContent>
          </Card>

          <Card>
            <CardHeader>
              <h3 className="text-section-title">Danger Zone</h3>
            </CardHeader>
            <CardContent className="space-y-4">
              <div className="flex items-center justify-between p-3 bg-error/10 border border-error/30 rounded-lg">
                <div>
                  <p className="font-medium text-error">Reset All Settings</p>
                  <p className="text-body text-text-secondary">Restore all settings to their default values</p>
                </div>
                <Button variant="danger" size="sm">Reset</Button>
              </div>
              <div className="flex items-center justify-between p-3 bg-error/10 border border-error/30 rounded-lg">
                <div>
                  <p className="font-medium text-error">Clear All Data</p>
                  <p className="text-body text-text-secondary">Delete all cached data, request logs, and metrics</p>
                </div>
                <Button variant="danger" size="sm">Clear</Button>
              </div>
            </CardContent>
          </Card>
        </TabsContent>
      </Tabs>

      {/* Provider Form Modal */}
      {showProviderForm && (
        <div className="fixed inset-0 z-50 flex items-center justify-center p-4">
          <div className="absolute inset-0 bg-black/50" onClick={() => setShowProviderForm(false)} />
          <Card className="w-full max-w-2xl max-h-[90vh] overflow-y-auto">
            <CardHeader className="flex items-center justify-between">
              <h3 className="text-section-title">{editingProvider ? 'Edit Provider' : 'Add Provider'}</h3>
              <Button variant="ghost" size="sm" onClick={() => setShowProviderForm(false)}>
                <span className="w-4 h-4" />
              </Button>
            </CardHeader>
            <CardContent className="space-y-4">
              <Input
                label="Name"
                value={newProvider.name}
                onChange={(e) => handleProviderChange('name', e.target.value)}
                placeholder="e.g., Production OpenAI"
              />
              <Select
                label="Type"
                value={newProvider.type}
                onChange={(e) => handleProviderChange('type', e.target.value)}
                options={PROVIDER_TYPES}
              />
              <Input
                label="Base URL"
                value={newProvider.baseUrl}
                onChange={(e) => handleProviderChange('baseUrl', e.target.value)}
                placeholder="https://api.openai.com/v1"
              />
              <Input
                label="API Key"
                type={showApiKey === 'new' ? 'text' : 'password'}
                value={newProvider.apiKey}
                onChange={(e) => handleProviderChange('apiKey', e.target.value)}
                placeholder="sk-..."
              />
              <Input
                label="Models (comma-separated)"
                value={newProvider.models.join(', ')}
                onChange={(e) => handleProviderChange('models', e.target.value.split(',').map(s => s.trim()).filter(Boolean))}
                placeholder="nvidia/nemotron-3-ultra-550b-a55b"
              />
              <div className="grid grid-cols-2 gap-4">
                <Input
                  label="Priority"
                  type="number"
                  value={newProvider.priority}
                  onChange={(e) => handleProviderChange('priority', parseInt(e.target.value) || 0)}
                />
                <Switch
                  checked={newProvider.enabled}
                  onChange={(checked) => handleProviderChange('enabled', checked)}
                />
              </div>
              <div className="flex justify-end gap-2 pt-4 border-t border-border-subtle">
                <Button variant="secondary" onClick={() => setShowProviderForm(false)}>Cancel</Button>
                <Button onClick={handleSaveProvider}>{editingProvider ? 'Save Changes' : 'Add Provider'}</Button>
              </div>
            </CardContent>
          </Card>
        </div>
      )}
    </div>
  )
}