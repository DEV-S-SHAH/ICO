// Playground Page

import { useEffect, useState } from 'react'
import {
  Terminal,
  Send,
  Zap,
  Copy,
  Check,
  Loader2,
  Trash2,
  ChevronDown,
  ChevronUp,
} from 'lucide-react'
import { cn } from '@/components/common'
import { formatNumber, formatDuration, formatCurrency, formatPercent, jsonStringify } from '@/lib/formatters'
import {
  Button,
  Input,
  Select,
  Badge,
  Card,
  CardContent,
  Divider,
  Tabs,
  TabsList,
  TabsTrigger,
  TabsContent,
  Textarea,
} from '@/components/common'
import { useUIStore, usePlaygroundStore } from '@/lib/stores'
import { getApiClient } from '@/lib/api/client'
import type { Request } from '@/types'

const MODEL_OPTIONS = [
  { value: 'claude-sonnet-4.6', label: 'Claude Sonnet 4.6', provider: 'Anthropic', endpoint: '/v1/messages' },
  { value: 'claude-opus-4.5', label: 'Claude Opus 4.5', provider: 'Anthropic', endpoint: '/v1/messages' },
  { value: 'gpt-5', label: 'GPT-5', provider: 'OpenAI', endpoint: '/v1/chat/completions' },
  { value: 'gpt-5-mini', label: 'GPT-5 Mini', provider: 'OpenAI', endpoint: '/v1/chat/completions' },
  { value: 'gemini-2.5-pro', label: 'Gemini 2.5 Pro', provider: 'Google', endpoint: '/v1/chat/completions' },
  { value: 'gemini-2.5-flash', label: 'Gemini 2.5 Flash', provider: 'Google', endpoint: '/v1/chat/completions' },
  { value: 'llama-3.1-405b', label: 'Llama 3.1 405B', provider: 'Meta', endpoint: '/v1/chat/completions' },
  { value: 'llama-3.1-70b', label: 'Llama 3.1 70B', provider: 'Meta', endpoint: '/v1/chat/completions' },
  { value: 'qwen-2.5-72b', label: 'Qwen 2.5 72B', provider: 'Alibaba', endpoint: '/v1/chat/completions' },
  { value: 'mistral-large-2', label: 'Mistral Large 2', provider: 'Mistral', endpoint: '/v1/chat/completions' },
]

export function Playground() {
  const { demoMode } = useUIStore()
  const {
    model,
    provider,
    endpoint,
    systemPrompt,
    userPrompt,
    temperature,
    maxTokens,
    response,
    loading,
    error,
    setModel,
    setProvider,
    setEndpoint,
    setSystemPrompt,
    setUserPrompt,
    setTemperature,
    setMaxTokens,
    setResponse,
    setLoading,
    setError,
    reset,
  } = usePlaygroundStore()

  const [copied, setCopied] = useState(false)
  const [showAdvanced, setShowAdvanced] = useState(false)
  const [responseTabs, setResponseTabs] = useState<'response' | 'raw' | 'trace'>('response')

  // Update provider/endpoint when model changes
  useEffect(() => {
    const selected = MODEL_OPTIONS.find(m => m.value === model)
    if (selected) {
      setProvider(selected.provider)
      setEndpoint(selected.endpoint)
    }
  }, [model, setProvider, setEndpoint])

  const handleSend = async () => {
    if (!userPrompt.trim() || loading) return

    setLoading(true)
    setError(null)

    try {
      const api = getApiClient(demoMode)
      const result = await api.sendPlaygroundRequest({
        model,
        provider,
        endpoint,
        systemPrompt,
        userPrompt,
        temperature,
        maxTokens,
      })
      setResponse(result)
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to send request')
    } finally {
      setLoading(false)
    }
  }

  const handleCopy = async (text: string) => {
    await navigator.clipboard.writeText(text)
    setCopied(true)
    setTimeout(() => setCopied(false), 2000)
  }

  const formatResponse = (req: Request) => {
    if (!req.responseBody) return 'No response'
    try {
      const body = req.responseBody as { choices?: Array<{ message?: { content: string } }> }
      return body.choices?.[0]?.message?.content || JSON.stringify(req.responseBody, null, 2)
    } catch {
      return JSON.stringify(req.responseBody, null, 2)
    }
  }

  return (
    <div className="space-y-6">
      {/* Page Header */}
      <div className="page-header">
        <div>
          <h1 className="page-title flex items-center gap-2">
            <Terminal className="w-6 h-6" />
            Playground
          </h1>
          <p className="page-description">Test models, compare responses, and inspect cache behavior in real-time</p>
        </div>
        <Button variant="ghost" size="sm" onClick={reset}>
          <Trash2 className="w-4 h-4 mr-1" />
          Clear
        </Button>
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        {/* Left Panel - Input */}
        <Card className="flex flex-col h-full">
          <CardContent className="flex-1 p-4 space-y-4 overflow-y-auto">
            {/* Model Selection */}
            <div className="space-y-3">
              <label className="text-metadata text-text-muted">MODEL</label>
              <Select
                value={model}
                onChange={(e) => setModel(e.target.value)}
                options={MODEL_OPTIONS.map(m => ({ value: m.value, label: m.label }))}
                className="w-full"
              />
              <div className="flex items-center gap-3 text-metadata text-text-muted">
                <span>Provider: <code className="code">{provider}</code></span>
                <span>Endpoint: <code className="code">{endpoint}</code></span>
              </div>
            </div>

            <Divider />

            {/* System Prompt */}
            <div className="space-y-2">
              <label className="text-metadata text-text-muted">SYSTEM PROMPT</label>
              <Textarea
                value={systemPrompt}
                onChange={(e) => setSystemPrompt(e.target.value)}
                placeholder="System instructions..."
                rows={4}
                className="font-mono text-code"
              />
            </div>

            <Divider />

            {/* User Prompt */}
            <div className="space-y-2">
              <label className="text-metadata text-text-muted">USER PROMPT</label>
              <Textarea
                value={userPrompt}
                onChange={(e) => setUserPrompt(e.target.value)}
                placeholder="Enter your prompt..."
                rows={6}
                className="font-mono text-code"
              />
            </div>

            {/* Advanced Options */}
            <div className="border-t border-border-subtle pt-4">
              <Button
                variant="ghost"
                size="sm"
                className="w-full justify-between"
                onClick={() => setShowAdvanced(!showAdvanced)}
              >
                <span>Advanced Options</span>
                {showAdvanced ? <ChevronUp className="w-4 h-4" /> : <ChevronDown className="w-4 h-4" />}
              </Button>

              {showAdvanced && (
                <div className="grid grid-cols-2 gap-4 mt-4">
                  <div className="space-y-2">
                    <label className="text-metadata text-text-muted">Temperature</label>
                    <div className="flex items-center gap-3">
                      <input
                        type="range"
                        min="0"
                        max="2"
                        step="0.1"
                        value={temperature}
                        onChange={(e) => setTemperature(parseFloat(e.target.value))}
                        className="flex-1 accent-accent"
                      />
                      <span className="font-mono text-code w-10 text-right">{temperature.toFixed(1)}</span>
                    </div>
                  </div>
                  <div className="space-y-2">
                    <label className="text-metadata text-text-muted">Max Tokens</label>
                    <Input
                      type="number"
                      value={maxTokens}
                      onChange={(e) => setMaxTokens(parseInt(e.target.value) || 0)}
                      min={1}
                      max={8192}
                      className="font-mono"
                    />
                  </div>
                </div>
              )}
            </div>

            {/* Send Button */}
            <Button
              className="w-full py-3"
              onClick={handleSend}
              disabled={loading || !userPrompt.trim()}
            >
              {loading ? (
                <>
                  <Loader2 className="w-4 h-4 animate-spin" />
                  Sending...
                </>
              ) : (
                <>
                  <Send className="w-4 h-4" />
                  Send Request
                </>
              )}
            </Button>

            {error && (
              <div className="p-3 bg-error/10 border border-error/30 rounded-md text-error text-body">
                {error}
              </div>
            )}
          </CardContent>
        </Card>

        {/* Right Panel - Response */}
        <Card className="flex flex-col h-full">
          {response ? (
            <>
              <CardContent className="p-4 space-y-4">
                {/* Response Header */}
                <div className="flex items-center justify-between">
                  <h3 className="text-section-title">Response</h3>
                  <div className="flex items-center gap-2">
                    <Badge variant={response.cache.status === 'HIT' ? 'success' : 'warning'} dot>
                      {response.cache.layer ? `${response.cache.layer} ${response.cache.status}` : response.cache.status}
                    </Badge>
                    {response.cache.similarity && (
                      <Badge variant="info">{formatPercent(response.cache.similarity)} similarity</Badge>
                    )}
                  </div>
                </div>

                {/* Metrics */}
                <div className="grid grid-cols-3 gap-4 p-3 bg-bg-elevated rounded-lg">
                  <div className="text-center">
                    <p className="text-2xl font-semibold font-mono tabular-nums">{formatDuration(response.latency)}</p>
                    <p className="text-metadata text-text-muted">Latency</p>
                  </div>
                  <div className="text-center">
                    <p className="text-2xl font-semibold font-mono tabular-nums">{formatCurrency(response.cost.total)}</p>
                    <p className="text-metadata text-text-muted">Cost</p>
                  </div>
                  <div className="text-center">
                    <p className="text-2xl font-semibold font-mono tabular-nums">{formatNumber(response.tokens.total)}</p>
                    <p className="text-metadata text-text-muted">Tokens</p>
                  </div>
                </div>

                <Divider />

                {/* Response Tabs */}
                <Tabs value={responseTabs} onValueChange={setResponseTabs}>
                  <TabsList>
                    <TabsTrigger value="response">Response</TabsTrigger>
                    <TabsTrigger value="raw">Raw JSON</TabsTrigger>
                    <TabsTrigger value="trace">Trace</TabsTrigger>
                  </TabsList>

                  <TabsContent value="response" className="mt-4">
                    <div className="prose prose-dark max-w-none p-4 bg-bg-elevated rounded-lg min-h-[200px] font-mono text-code whitespace-pre-wrap">
                      {formatResponse(response)}
                    </div>
                    <div className="flex justify-end gap-2 mt-3">
                      <Button variant="ghost" size="sm" onClick={() => handleCopy(formatResponse(response))}>
                        {copied ? <Check className="w-4 h-4" /> : <Copy className="w-4 h-4" />}
                        {copied ? 'Copied' : 'Copy'}
                      </Button>
                    </div>
                  </TabsContent>

                  <TabsContent value="raw" className="mt-4">
                    <div className="p-4 bg-bg-elevated rounded-lg font-mono text-code text-sm overflow-auto max-h-96">
                      <pre>{jsonStringify(response.responseBody)}</pre>
                    </div>
                    <div className="flex justify-end gap-2 mt-3">
                      <Button variant="ghost" size="sm" onClick={() => handleCopy(jsonStringify(response.responseBody))}>
                        {copied ? <Check className="w-4 h-4" /> : <Copy className="w-4 h-4" />}
                        {copied ? 'Copied' : 'Copy'}
                      </Button>
                    </div>
                  </TabsContent>

                  <TabsContent value="trace" className="mt-4">
                    {response.trace && (
                      <div className="space-y-2">
                        {response.trace.children?.map((node, i) => (
                          <div key={i} className="p-3 bg-bg-elevated rounded-lg border-l-2 border-accent">
                            <div className="flex items-center gap-2 mb-1">
                              <span className="font-mono font-medium">{node.name}</span>
                              <span className="font-mono text-metadata text-text-muted">{node.duration}ms</span>
                              {node.result && <span className="text-metadata text-text-secondary">{node.result}</span>}
                            </div>
                            {node.children && node.children.map((child, j) => (
                              <div key={j} className="ml-4 mt-2 pt-2 border-l border-border-subtle pl-2">
                                <div className="flex items-center gap-2">
                                  <span className="font-mono text-body">{child.name}</span>
                                  <span className="font-mono text-metadata text-text-muted">{child.duration}ms</span>
                                  {child.result && <span className="text-metadata text-text-secondary">{child.result}</span>}
                                </div>
                              </div>
                            ))}
                          </div>
                        ))}
                      </div>
                    )}
                  </TabsContent>
                </Tabs>

                {/* Cache Details */}
                <Divider />
                <div className="space-y-3">
                  <h4 className="text-body font-medium text-text-secondary">Cache Details</h4>
                  <div className="grid grid-cols-2 gap-3 text-metadata">
                    <div className="p-3 bg-bg-elevated rounded-lg">
                      <p className="text-text-muted">Tokens Saved</p>
                      <p className="font-mono font-medium text-success">{formatNumber(response.tokens.cachedInput)}</p>
                    </div>
                    <div className="p-3 bg-bg-elevated rounded-lg">
                      <p className="text-text-muted">Latency Saved</p>
                      <p className="font-mono font-medium">{response.cache.latencySaved ? `${response.cache.latencySaved}ms` : '—'}</p>
                    </div>
                    <div className="p-3 bg-bg-elevated rounded-lg">
                      <p className="text-text-muted">Cache Layer</p>
                      <p className="font-mono font-medium">{response.cache.layer || 'None'}</p>
                    </div>
                    <div className="p-3 bg-bg-elevated rounded-lg">
                      <p className="text-text-muted">Cost Saved</p>
                      <p className="font-mono font-medium text-success">{formatCurrency(response.cost.saved)}</p>
                    </div>
                  </div>
                </div>
              </CardContent>
            </>
          ) : (
            <div className="flex-1 flex items-center justify-center p-8">
              <div className="text-center">
                <Zap className="w-16 h-16 text-text-muted/20 mx-auto mb-4" />
                <h3 className="text-section-title mb-2">Ready to Test</h3>
                <p className="text-text-secondary">Configure your model and prompt on the left, then click Send Request</p>
              </div>
            </div>
          )}
        </Card>
      </div>
    </div>
  )
}