// Configuration Page

import React, { useState } from 'react'
import {
  Settings as SettingsIcon,
  SlidersHorizontal,
  Database,
  Zap,
  Shield,
  Network,
  Save,
  RefreshCw,
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
  Switch,
} from '@/components/common'
import { useUIStore } from '@/lib/stores'

const CONFIG_SECTIONS = [
  { id: 'cache', label: 'Cache Configuration', icon: Database },
  { id: 'network', label: 'Network & Timeouts', icon: Network },
  { id: 'security', label: 'Security', icon: Shield },
  { id: 'performance', label: 'Performance Tuning', icon: Zap },
]

export function Configuration() {
  const { demoMode } = useUIStore()
  const [expandedSections, setExpandedSections] = useState<string[]>(['cache'])
  const [saving, setSaving] = useState(false)

  const toggleSection = (section: string) => {
    setExpandedSections(prev => 
      prev.includes(section) ? prev.filter(s => s !== section) : [...prev, section]
    )
  }

  const handleSave = async () => {
    setSaving(true)
    await new Promise(r => setTimeout(r, 1000))
    setSaving(false)
  }

  return (
    <div className="space-y-6">
      {/* Page Header */}
      <div className="page-header">
        <div>
          <h1 className="page-title flex items-center gap-2">
            <SettingsIcon className="w-6 h-6" />
            Configuration
          </h1>
          <p className="page-description">Configure cache behavior, network settings, and system parameters</p>
        </div>
        <div className="flex items-center gap-2">
          <Button variant="secondary" size="sm" onClick={() => {}}>
            <RefreshCw className="w-4 h-4" />
            Reset to Defaults
          </Button>
          <Button onClick={handleSave} disabled={saving}>
            {saving ? 'Saving...' : <> <Save className="w-4 h-4 mr-1" /> Save Configuration </>}
          </Button>
        </div>
      </div>

      {/* Config Sections */}
      <div className="space-y-4">
        {CONFIG_SECTIONS.map(section => {
          const Icon = section.icon
          const isExpanded = expandedSections.includes(section.id)

          return (
            <Card key={section.id} className="overflow-hidden">
              <button
                onClick={() => toggleSection(section.id)}
                className="w-full p-4 flex items-center justify-between hover:bg-bg-elevated/50 transition-colors"
              >
                <div className="flex items-center gap-3">
                  <div className="w-10 h-10 rounded-lg bg-accent/10 flex items-center justify-center">
                    <Icon className="w-5 h-5 text-accent" />
                  </div>
                  <h3 className="font-medium">{section.label}</h3>
                </div>
                {isExpanded ? <ChevronUp className="w-5 h-5 text-text-muted" /> : <ChevronDown className="w-5 h-5 text-text-muted" />}
              </button>

              {isExpanded && (
                <CardContent className="pt-0 pb-4 px-4 space-y-6">
                  {section.id === 'cache' && (
                    <div className="space-y-6">
                      <h4 className="text-body font-medium text-text-secondary">Cache Layers</h4>
                      <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
                        {['L1', 'L2', 'L3'].map((layer, i) => (
                          <div key={layer} className="p-4 bg-bg-elevated rounded-lg border border-border-subtle">
                            <div className="flex items-center justify-between mb-4">
                              <h5 className="font-medium">{layer} {layer === 'L1' ? 'Exact Match' : layer === 'L2' ? 'Semantic Vector' : 'Context-Aware'}</h5>
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
                    </div>
                  )}

                  {section.id === 'network' && (
                    <div className="space-y-6">
                      <h4 className="text-body font-medium text-text-secondary">API Timeouts</h4>
                      <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
                        <Input label="Connect Timeout (ms)" type="number" value={5000} onChange={() => {}} />
                        <Input label="Read Timeout (ms)" type="number" value={30000} onChange={() => {}} />
                        <Input label="Write Timeout (ms)" type="number" value={10000} onChange={() => {}} />
                      </div>

                      <Divider />

                      <h4 className="text-body font-medium text-text-secondary">Retry Configuration</h4>
                      <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
                        <Input label="Max Retries" type="number" value={3} onChange={() => {}} />
                        <Input label="Base Delay (ms)" type="number" value={1000} onChange={() => {}} />
                        <Input label="Max Delay (ms)" type="number" value={30000} onChange={() => {}} />
                      </div>

                      <Divider />

                      <h4 className="text-body font-medium text-text-secondary">Connection Pooling</h4>
                      <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
                        <Input label="Max Connections" type="number" value={100} onChange={() => {}} />
                        <Input label="Max Idle Connections" type="number" value={10} onChange={() => {}} />
                        <Input label="Connection TTL (ms)" type="number" value={60000} onChange={() => {}} />
                      </div>
                    </div>
                  )}

                  {section.id === 'security' && (
                    <div className="space-y-6">
                      <h4 className="text-body font-medium text-text-secondary">Authentication</h4>
                      <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                        <Select
                          label="Auth Mode"
                          value="api_key"
                          options={[
                            { value: 'api_key', label: 'API Key' },
                            { value: 'jwt', label: 'JWT' },
                            { value: 'oauth2', label: 'OAuth 2.0' },
                            { value: 'mtls', label: 'mTLS' },
                          ]}
                        />
                        <Input
                          label="API Key Header"
                          value="X-API-Key"
                          onChange={() => {}}
                        />
                        <Input
                          label="JWT Issuer"
                          value="synapse-cache"
                          onChange={() => {}}
                        />
                        <Input
                          label="JWT Audience"
                          value="synapse-api"
                          onChange={() => {}}
                        />
                      </div>

                      <Divider />

                      <h4 className="text-body font-medium text-text-secondary">Tenant Isolation</h4>
                      <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                        <Switch label="Strict Tenant Isolation" checked={true} onChange={() => {}} />
                        <Switch label="Cross-Tenant Cache Sharing" checked={false} onChange={() => {}} />
                        <Input label="Default Tenant" value="default" onChange={() => {} } />
                      </div>

                      <Divider />

                      <h4 className="text-body font-medium text-text-secondary">Rate Limiting</h4>
                      <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
                        <Input label="Requests per Minute" type="number" value={1000} onChange={() => {}} />
                        <Input label="Burst Allowance" type="number" value={100} onChange={() => {}} />
                        <Select
                          label="Algorithm"
                          value="token_bucket"
                          options={[
                            { value: 'token_bucket', label: 'Token Bucket' },
                            { value: 'leaky_bucket', label: 'Leaky Bucket' },
                            { value: 'fixed_window', label: 'Fixed Window' },
                            { value: 'sliding_window', label: 'Sliding Window' },
                          ]}
                        />
                      </div>
                    </div>
                  )}

                  {section.id === 'performance' && (
                    <div className="space-y-6">
                      <h4 className="text-body font-medium text-text-secondary">Batching</h4>
                      <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
                        <Switch label="Enable Request Batching" checked={true} onChange={() => {}} />
                        <Input label="Max Batch Size" type="number" value={10} onChange={() => {}} />
                        <Input label="Batch Timeout (ms)" type="number" value={50} onChange={() => {}} />
                      </div>

                      <Divider />

                      <h4 className="text-body font-medium text-text-secondary">Compression</h4>
                      <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
                        <Switch label="Enable Response Compression" checked={true} onChange={() => {}} />
                        <Select
                          label="Compression Algorithm"
                          value="gzip"
                          options={[
                            { value: 'gzip', label: 'Gzip' },
                            { value: 'brotli', label: 'Brotli' },
                            { value: 'zstd', label: 'Zstandard' },
                          ]}
                        />
                        <Input label="Min Size (bytes)" type="number" value={1024} onChange={() => {}} />
                      </div>

                      <Divider />

                      <h4 className="text-body font-medium text-text-secondary">Worker Threads</h4>
                      <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
                        <Input label="Ingestion Workers" type="number" value={4} onChange={() => {}} />
                        <Input label="Cache Write Workers" type="number" value={2} onChange={() => {}} />
                        <Input label="Invalidation Workers" type="number" value={1} onChange={() => {}} />
                      </div>
                    </div>
                  )}
                </CardContent>
              )}
            </Card>
          )
        })}
      </div>
    </div>
  )
}