// API Keys Page

import React, { useState } from 'react'
import {
  Key,
  Plus,
  Copy,
  Eye,
  EyeOff,
  Trash2,
  Edit,
  RefreshCw,
  Shield,
  Clock,
  AlertTriangle,
} from 'lucide-react'
import { cn } from '@/components/common'
import {
  Button,
  Input,
  Badge,
  Card,
  CardContent,
  CardHeader,
  Divider,
  EmptyState,
  Switch,
  Select,
} from '@/components/common'
interface ApiKey {
  id: string
  name: string
  key: string
  prefix: string
  created: string
  lastUsed: string
  expires: string
  status: string
  scopes: string[]
  rateLimit: number
}

export function ApiKeys() {
  const [apiKeys, setApiKeys] = useState<ApiKey[]>([])
  const [showKey, setShowKey] = useState<string | null>(null)
  const [showCreateModal, setShowCreateModal] = useState(false)
  const [newKeyName, setNewKeyName] = useState('')
  const [newKeyScopes, setNewKeyScopes] = useState<string[]>(['read'])
  const [newKeyRateLimit, setNewKeyRateLimit] = useState(1000)
  const [newKeyExpires, setNewKeyExpires] = useState('30d')

  const maskKey = (key: string) => key.slice(0, 7) + '••••••••' + key.slice(-4)

  const generateKey = () => {
    const prefix = 'sk-'
    const chars = 'abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789'
    let result = prefix
    for (let i = 0; i < 32; i++) {
      result += chars.charAt(Math.floor(Math.random() * chars.length))
    }
    return result
  }

  const handleCreate = () => {
    const key = generateKey()
    const newKey = {
      id: `key-${Date.now()}`,
      name: newKeyName,
      key,
      prefix: key.slice(0, 8),
      created: new Date().toISOString().split('T')[0],
      lastUsed: 'Never',
      expires: newKeyExpires === 'never' ? 'Never' : new Date(Date.now() + parseInt(newKeyExpires) * 24 * 60 * 60 * 1000).toISOString().split('T')[0],
      status: 'active',
      scopes: newKeyScopes,
      rateLimit: newKeyRateLimit,
    }
    setApiKeys(prev => [...prev, newKey])
    setShowCreateModal(false)
    setNewKeyName('')
    setNewKeyScopes(['read'])
    setNewKeyRateLimit(1000)
    setNewKeyExpires('30d')
    alert(`New API Key created!\n\nKey: ${key}\n\nSave this key securely - it won't be shown again.`)
  }

  const handleCopy = async (key: string) => {
    await navigator.clipboard.writeText(key)
  }

  const handleRevoke = (id: string) => {
    if (confirm('Are you sure you want to revoke this API key? This action cannot be undone.')) {
      setApiKeys(prev => prev.filter(k => k.id !== id))
    }
  }

  const getStatusBadge = (status: string) => {
    switch (status) {
      case 'active': return <Badge variant="success" dot>Active</Badge>
      case 'expiring': return <Badge variant="warning" dot>Expiring Soon</Badge>
      case 'revoked': return <Badge variant="error" dot>Revoked</Badge>
      default: return <Badge variant="neutral">{status}</Badge>
    }
  }

  return (
    <div className="space-y-6">
      {/* Page Header */}
      <div className="page-header">
        <div>
          <h1 className="page-title flex items-center gap-2">
            <Key className="w-6 h-6" />
            API Keys
          </h1>
          <p className="page-description">Manage API keys for programmatic access to the cache infrastructure</p>
        </div>
        <Button onClick={() => setShowCreateModal(true)}>
          <Plus className="w-4 h-4 mr-2" />
          Create API Key
        </Button>
      </div>

      {/* Security Notice */}
      <Card className="border-accent/30 bg-accent/5">
        <CardContent className="pt-4">
          <div className="flex items-start gap-3">
            <Shield className="w-5 h-5 text-accent mt-0.5 flex-shrink-0" />
            <div>
              <p className="font-medium text-text-primary">Security Best Practices</p>
              <ul className="text-body text-text-secondary mt-2 space-y-1 list-disc list-inside">
                <li>Store API keys securely - they provide full access to your cache infrastructure</li>
                <li>Rotate keys regularly (every 90 days recommended)</li>
                <li>Use least-privilege scopes - only grant necessary permissions</li>
                <li>Monitor key usage and revoke unused keys</li>
                <li>Never commit API keys to version control</li>
              </ul>
            </div>
          </div>
        </CardContent>
      </Card>

      {/* API Keys List */}
      <div className="space-y-4">
        {apiKeys.length === 0 && (
          <Card>
            <CardContent className="pt-4">
              <EmptyState
                icon={<Key className="w-12 h-12" />}
                title="No API keys yet"
                description="This runtime has no key management backend. Use Create API Key to generate a client-side key for your own demo workflows."
              />
            </CardContent>
          </Card>
        )}
        {apiKeys.map((apiKey) => (
          <Card key={apiKey.id} className="p-4">
            <div className="flex items-start justify-between">
              <div className="flex items-center gap-4 flex-1">
                <div className="w-12 h-12 rounded-lg bg-accent/10 flex items-center justify-center">
                  <Key className="w-6 h-6 text-accent" />
                </div>
                <div>
                  <div className="flex items-center gap-2">
                    <h3 className="font-medium">{apiKey.name}</h3>
                    {getStatusBadge(apiKey.status)}
                  </div>
                  <p className="text-metadata text-text-muted mt-1">
                    Created {apiKey.created} • Last used: {apiKey.lastUsed} • Expires: {apiKey.expires}
                  </p>
                  <div className="flex items-center gap-3 mt-2 text-metadata">
                    <span className="flex items-center gap-1">
                      <Shield className="w-3 h-3" />
                      Scopes: {apiKey.scopes.join(', ')}
                    </span>
                    <span className="flex items-center gap-1">
                      <Clock className="w-3 h-3" />
                      Rate limit: {apiKey.rateLimit.toLocaleString()}/min
                    </span>
                  </div>
                </div>
              </div>

              <div className="flex items-center gap-2">
                <div className="relative">
                  <code className="code mr-2">{showKey === apiKey.id ? apiKey.key : maskKey(apiKey.key)}</code>
                  <Button
                    variant="ghost"
                    size="sm"
                    onClick={() => setShowKey(showKey === apiKey.id ? null : apiKey.id)}
                  >
                    {showKey === apiKey.id ? <EyeOff className="w-4 h-4" /> : <Eye className="w-4 h-4" />}
                  </Button>
                </div>
                <Button variant="ghost" size="sm" onClick={() => handleCopy(apiKey.key)}>
                  <Copy className="w-4 h-4" />
                </Button>
                {apiKey.status === 'active' && (
                  <Button variant="ghost" size="sm" onClick={() => {}}>
                    <Edit className="w-4 h-4" />
                  </Button>
                )}
                <Button variant="ghost" size="sm" onClick={() => handleRevoke(apiKey.id)}>
                  <Trash2 className="w-4 h-4" />
                </Button>
              </div>
            </div>
          </Card>
        ))}
      </div>

      {/* Create Modal */}
      {showCreateModal && (
        <div className="fixed inset-0 z-50 flex items-center justify-center p-4">
          <div className="absolute inset-0 bg-black/50" onClick={() => setShowCreateModal(false)} />
          <Card className="w-full max-w-md">
            <CardHeader className="flex items-center justify-between">
              <h3 className="text-section-title">Create API Key</h3>
              <Button variant="ghost" size="sm" onClick={() => setShowCreateModal(false)}>
                <span className="w-4 h-4" />
              </Button>
            </CardHeader>
            <CardContent className="space-y-4">
              <Input
                label="Key Name"
                value={newKeyName}
                onChange={(e) => setNewKeyName(e.target.value)}
                placeholder="e.g., Production API Key"
              />
              <div className="space-y-2">
                <label className="text-metadata text-text-muted">Scopes</label>
                <div className="flex flex-wrap gap-2">
                  {['read', 'write', 'admin', 'cache:read', 'cache:write', 'models:read'].map(scope => (
                    <label key={scope} className="flex items-center gap-2 cursor-pointer">
                      <input
                        type="checkbox"
                        checked={newKeyScopes.includes(scope)}
                        onChange={(e) => setNewKeyScopes(e.target.checked ? [...newKeyScopes, scope] : newKeyScopes.filter(s => s !== scope))}
                        className="rounded border-border-subtle text-accent focus:ring-accent"
                      />
                      <span className="text-body capitalize">{scope}</span>
                    </label>
                  ))}
                </div>
              </div>
              <Input
                label="Rate Limit (requests/min)"
                type="number"
                value={newKeyRateLimit}
                onChange={(e) => setNewKeyRateLimit(parseInt(e.target.value) || 1000)}
              />
              <Select
                label="Expires In"
                value={newKeyExpires}
                onChange={(e) => setNewKeyExpires(e.target.value)}
                options={[
                  { value: 'never', label: 'Never' },
                  { value: '7', label: '7 Days' },
                  { value: '30', label: '30 Days' },
                  { value: '90', label: '90 Days' },
                  { value: '365', label: '1 Year' },
                ]}
              />
              <Divider />
              <div className="flex justify-end gap-2">
                <Button variant="secondary" onClick={() => setShowCreateModal(false)}>Cancel</Button>
                <Button onClick={handleCreate} disabled={!newKeyName.trim()}>
                  <Key className="w-4 h-4 mr-2" />
                  Create Key
                </Button>
              </div>
            </CardContent>
          </Card>
        </div>
      )}
    </div>
  )
}