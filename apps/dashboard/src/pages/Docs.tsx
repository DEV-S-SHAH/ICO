// Docs Page

import React from 'react'
import {
  BookOpen,
  FileText,
  Code,
  ExternalLink,
  Search,
  ChevronRight,
  Copy,
  Github,
  Terminal,
} from 'lucide-react'
import { cn } from '@/components/common'
import {
  Button,
  Input,
  Badge,
  Card,
  CardContent,
  Tabs,
  TabsList,
  TabsTrigger,
} from '@/components/common'

const DOC_SECTIONS = [
  {
    id: 'getting-started',
    label: 'Getting Started',
    items: [
      { title: 'Quick Start', description: 'Get up and running in 5 minutes', href: '#', type: 'guide' },
      { title: 'Installation', description: 'Install the SDK and CLI tools', href: '#', type: 'guide' },
      { title: 'Configuration', description: 'Configure cache layers and policies', href: '#', type: 'config' },
      { title: 'First Request', description: 'Make your first cached request', href: '#', type: 'example' },
    ]
  },
  {
    id: 'cache-layers',
    label: 'Cache Layers',
    items: [
      { title: 'L1 - Exact Match Cache', description: 'Hash-based exact deduplication', href: '#', type: 'concept' },
      { title: 'L2 - Semantic Vector Cache', description: 'Embedding-based similarity matching', href: '#', type: 'concept' },
      { title: 'L3 - Context-Aware Cache', description: 'RAG-enhanced contextual caching', href: '#', type: 'concept' },
      { title: 'Cache Invalidation', description: 'Strategies for keeping cache fresh', href: '#', type: 'guide' },
    ]
  },
  {
    id: 'api-reference',
    label: 'API Reference',
    items: [
      { title: 'REST API', description: 'Complete REST endpoint documentation', href: '#', type: 'reference' },
      { title: 'Python SDK', description: 'Python client library reference', href: '#', type: 'reference' },
      { title: 'JavaScript SDK', description: 'TypeScript/JavaScript client library', href: '#', type: 'reference' },
      { title: 'Webhooks', description: 'Real-time event notifications', href: '#', type: 'reference' },
    ]
  },
  {
    id: 'integrations',
    label: 'Integrations',
    items: [
      { title: 'OpenAI', description: 'Cache OpenAI completions and embeddings', href: '#', type: 'integration' },
      { title: 'Anthropic', description: 'Cache Claude requests and responses', href: '#', type: 'integration' },
      { title: 'LangChain', description: 'LangChain callback handler', href: '#', type: 'integration' },
      { title: 'LlamaIndex', description: 'LlamaIndex cache integration', href: '#', type: 'integration' },
      { title: 'Vercel AI SDK', description: 'Vercel AI SDK middleware', href: '#', type: 'integration' },
    ]
  },
  {
    id: 'deployment',
    label: 'Deployment',
    items: [
      { title: 'Docker', description: 'Containerized deployment', href: '#', type: 'guide' },
      { title: 'Kubernetes (Helm)', description: 'Production Helm charts', href: '#', type: 'guide' },
      { title: 'Cloud Providers', description: 'AWS, GCP, Azure deployment guides', href: '#', type: 'guide' },
      { title: 'Observability', description: 'Metrics, logging, and tracing setup', href: '#', type: 'guide' },
    ]
  },
]

const TYPE_LABELS: Record<string, { label: string; color: string }> = {
  guide: { label: 'Guide', color: 'bg-blue-500/20 text-blue-400' },
  concept: { label: 'Concept', color: 'bg-purple-500/20 text-purple-400' },
  reference: { label: 'Reference', color: 'bg-gray-500/20 text-gray-400' },
  example: { label: 'Example', color: 'bg-green-500/20 text-green-400' },
  config: { label: 'Config', color: 'bg-orange-500/20 text-orange-400' },
  integration: { label: 'Integration', color: 'bg-pink-500/20 text-pink-400' },
}

export function Docs() {
  const [search, setSearch] = React.useState('')
  const [activeTab, setActiveTab] = React.useState('getting-started')

  const filteredSections = React.useMemo(() => {
    if (!search) return DOC_SECTIONS
    const s = search.toLowerCase()
    return DOC_SECTIONS.map(section => ({
      ...section,
      items: section.items.filter(item => 
        item.title.toLowerCase().includes(s) || 
        item.description.toLowerCase().includes(s)
      )
    })).filter(section => section.items.length > 0)
  }, [search])

  return (
    <div className="space-y-6">
      {/* Page Header */}
      <div className="page-header">
        <div>
          <h1 className="page-title flex items-center gap-2">
            <BookOpen className="w-6 h-6" />
            Documentation
          </h1>
          <p className="page-description">Learn how to integrate and configure the semantic cache</p>
        </div>
        <div className="flex items-center gap-2">
          <Button variant="secondary" size="sm" className="gap-2">
            <Github className="w-4 h-4" />
            View on GitHub
          </Button>
          <Button variant="secondary" size="sm" className="gap-2">
            <Terminal className="w-4 h-4" />
            CLI Reference
          </Button>
        </div>
      </div>

      {/* Search */}
      <Card>
        <CardContent className="pt-4">
          <div className="relative max-w-2xl">
            <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-5 h-5 text-text-muted" />
            <Input
              placeholder="Search documentation..."
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              className="pl-10"
            />
          </div>
        </CardContent>
      </Card>

      {/* Tabs Navigation */}
      <Tabs defaultValue={activeTab} value={activeTab} onValueChange={setActiveTab} className="border-b border-border-subtle">
        <TabsList className="grid w-full gap-0">
          {DOC_SECTIONS.map(section => (
            <TabsTrigger key={section.id} value={section.id} className="py-3 px-4">
              {section.label}
            </TabsTrigger>
          ))}
        </TabsList>
      </Tabs>

      {/* Content */}
      <div className="space-y-4">
        {filteredSections.map(section => (
          <Card key={section.id}>
            <CardContent className="pt-4 pb-4">
              <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
                {section.items.map(item => {
                  const typeInfo = TYPE_LABELS[item.type]
                  return (
                    <div key={item.title} className="group p-4 rounded-lg border border-border-subtle hover:border-accent/50 hover:bg-bg-elevated/50 transition-all">
                      <div className="flex items-start gap-3">
                        <div className="w-10 h-10 rounded-lg bg-accent/10 flex items-center justify-center flex-shrink-0">
                          {item.type === 'guide' && <FileText className="w-5 h-5 text-accent" />}
                          {item.type === 'concept' && <BookOpen className="w-5 h-5 text-accent" />}
                          {item.type === 'reference' && <Code className="w-5 h-5 text-accent" />}
                          {item.type === 'example' && <Terminal className="w-5 h-5 text-accent" />}
                          {item.type === 'config' && <FileText className="w-5 h-5 text-accent" />}
                          {item.type === 'integration' && <Github className="w-5 h-5 text-accent" />}
                        </div>
                        <div className="flex-1 min-w-0">
                          <div className="flex items-center gap-2 mb-2">
                            <h4 className="font-medium group-hover:text-accent transition-colors">{item.title}</h4>
                            <Badge className={typeInfo.color}>{typeInfo.label}</Badge>
                          </div>
                          <p className="text-body text-text-secondary line-clamp-2">{item.description}</p>
                        </div>
                      </div>
                      <div className="flex items-center justify-end gap-2 mt-3 pt-3 border-t border-border-subtle">
                        <Button variant="ghost" size="sm" onClick={() => {}}>
                          <Copy className="w-4 h-4 mr-1" />
                          Link
                        </Button>
                        <Button variant="ghost" size="sm" onClick={() => {}}>
                          Read <ChevronRight className="w-3 h-3 ml-1" />
                        </Button>
                      </div>
                    </div>
                  )
                })}
              </div>
            </CardContent>
          </Card>
        ))}
      </div>

      {/* Quick Links */}
      <Card>
        <CardContent className="pt-4">
          <h3 className="font-medium mb-4">Quick Links</h3>
          <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-3">
            {[
              { label: 'API Reference', href: '#', icon: Code },
              { label: 'Python SDK Docs', href: '#', icon: FileText },
              { label: 'JS/TS SDK Docs', href: '#', icon: FileText },
              { label: 'Changelog', href: '#', icon: BookOpen },
              { label: 'Migration Guide', href: '#', icon: ChevronRight },
              { label: 'Troubleshooting', href: '#', icon: FileText },
              { label: 'Community Discord', href: '#', icon: ExternalLink },
              { label: 'Status Page', href: '#', icon: ExternalLink },
            ].map(link => (
              <Button key={link.label} variant="ghost" className="justify-start gap-3" onClick={() => {}}>
                <link.icon className="w-4 h-4" />
                {link.label}
              </Button>
            ))}
          </div>
        </CardContent>
      </Card>
    </div>
  )
}