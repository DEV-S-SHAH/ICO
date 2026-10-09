// Layout components

import React from 'react'
import { Navigate, Outlet, useLocation, Link } from 'react-router-dom'
import {
  LayoutDashboard,
  History,
  Database,
  Cpu,
  DollarSign,
  BarChart3,
  Server,
  Globe,
  Key,
  Settings,
  Terminal,
  BookOpen,
  Webhook,
  FileText,
  Activity,
  ChevronLeft,
  ChevronRight,
  Sun,
  Moon,
  Monitor,
  Zap,
} from 'lucide-react'
import { cn } from '@/components/common'
import { useUIStore } from '@/lib/stores'
import { Button } from '@/components/common'

const navigation = [
  {
    group: 'DASHBOARD',
    items: [
      { key: 'overview', label: 'Overview', icon: LayoutDashboard, href: '/', description: 'System overview & metrics' },
      { key: 'requests', label: 'Requests', icon: History, href: '/requests', description: 'Request logs & analysis' },
      { key: 'cache', label: 'Cache', icon: Database, href: '/cache', description: 'Cache performance & entries' },
      { key: 'models', label: 'Models', icon: Cpu, href: '/models', description: 'Model usage & metrics' },
      { key: 'costs', label: 'Costs', icon: DollarSign, href: '/costs', description: 'Cost analysis & usage' },
      { key: 'analytics', label: 'Analytics', icon: BarChart3, href: '/analytics', description: 'Advanced analytics' },
    ],
  },
  {
    group: 'INFRASTRUCTURE',
    items: [
      { key: 'providers', label: 'Providers', icon: Server, href: '/providers', description: 'LLM provider management' },
      { key: 'endpoints', label: 'Endpoints', icon: Globe, href: '/endpoints', description: 'API endpoint configuration' },
      { key: 'api-keys', label: 'API Keys', icon: Key, href: '/api-keys', description: 'API key management' },
      { key: 'configuration', label: 'Configuration', icon: Settings, href: '/configuration', description: 'System configuration' },
    ],
  },
  {
    group: 'DEVELOPER',
    items: [
      { key: 'playground', label: 'Playground', icon: Terminal, href: '/playground', description: 'Test & experiment' },
      { key: 'docs', label: 'Documentation', icon: BookOpen, href: '/docs', description: 'Documentation & guides' },
      { key: 'webhooks', label: 'Webhooks', icon: Webhook, href: '/webhooks', description: 'Webhook management' },
      { key: 'logs', label: 'Logs', icon: FileText, href: '/logs', description: 'System logs' },
    ],
  },
  {
    group: 'SYSTEM',
    items: [
      { key: 'settings', label: 'Settings', icon: Settings, href: '/settings', description: 'User preferences' },
      { key: 'status', label: 'Status', icon: Activity, href: '/status', description: 'System health status' },
    ],
  },
] as const

interface SidebarProps {
  collapsed?: boolean
  onToggle?: () => void
}

export function Sidebar({ collapsed: propCollapsed = false, onToggle }: SidebarProps) {
  const location = useLocation()
  const { sidebarCollapsed, toggleSidebar, environment } = useUIStore()

  const isActive = (href: string) => {
    if (href === '/') return location.pathname === '/'
    return location.pathname.startsWith(href)
  }

  // Keep sidebar permanently expanded so navigation links never disappear
  const collapsed = false

  return (
    <aside
      className="fixed left-0 top-0 z-40 h-full bg-bg-sidebar border-r border-border-subtle flex flex-col w-[248px]"
      aria-label="Main navigation"
    >
      {/* Logo */}
      <div className="flex items-center gap-3 px-4 py-4 border-b border-border-subtle">
        <div className="flex items-center gap-2">
          <div className="relative w-8 h-8 rounded-lg bg-accent/20 flex items-center justify-center">
            <Zap className="w-5 h-5 text-accent" />
          </div>
          <div className="flex flex-col min-w-0">
            <span className="text-body font-semibold text-text-primary truncate">SYNAPSE</span>
            <span className="text-metadata text-text-muted truncate">AI Cache Infrastructure</span>
          </div>
        </div>
      </div>

      {/* Navigation */}
      <nav className="flex-1 overflow-y-auto px-3 py-4 space-y-6" aria-label="Navigation">
        {navigation.map((section) => (
          <div key={section.group} className="space-y-1">
            <div className="px-2 py-1 text-metadata font-medium text-text-muted uppercase tracking-wider">
              {section.group}
            </div>
            <ul className="space-y-1" role="list">
              {section.items.map((item) => {
                const active = isActive(item.href)
                const Icon = item.icon
                return (
                  <li key={item.key}>
                    <Link
                      to={item.href}
                      className={cn(
                        'flex items-center gap-3 px-2 py-2 rounded-md transition-colors duration-fast',
                        'group relative overflow-hidden',
                        active
                          ? 'bg-accent/10 text-text-primary font-medium'
                          : 'text-text-secondary hover:text-text-primary hover:bg-bg-elevated'
                      )}
                      aria-current={active ? 'page' : undefined}
                    >
                      <Icon className={cn('w-5 h-5 flex-shrink-0', active ? 'text-accent' : 'text-text-muted group-hover:text-text-primary')} aria-hidden="true" />
                      <span className="text-body truncate">{item.label}</span>
                      {active && (
                        <span className="absolute left-0 top-0 bottom-0 w-0.5 bg-accent" aria-hidden="true" />
                      )}
                    </Link>
                  </li>
                )
              })}
            </ul>
          </div>
        ))}
      </nav>
    </aside>
  )
}

// Header component
interface HeaderProps {
  title?: string
  description?: string
  actions?: React.ReactNode
}

export function Header({ title, description, actions }: HeaderProps) {
  const { environment, setEnvironment, theme, setTheme, connected, latestLiveRequest } = useUIStore()

  const environments: Array<{ value: 'development' | 'staging' | 'production'; label: string; icon: React.ReactNode }> = [
    { value: 'development', label: 'Development', icon: <Monitor className="w-4 h-4" /> },
    { value: 'staging', label: 'Staging', icon: <Zap className="w-4 h-4" /> },
    { value: 'production', label: 'Production', icon: <Activity className="w-4 h-4" /> },
  ]

  return (
    <header className="sticky top-0 z-30 h-16 bg-bg-secondary/80 backdrop-blur-sm border-b border-border-subtle flex items-center">
      <div className="flex-1 px-6 flex items-center gap-4 min-w-0">
        {title ? (
          <div>
            <h1 className="text-page-title">{title}</h1>
            {description && <p className="text-body text-text-secondary mt-0.5">{description}</p>}
          </div>
        ) : null}

        {/* Live Incoming Request Ticker */}
        {latestLiveRequest && (
          <div className="flex items-center gap-2.5 px-3 py-1.5 rounded-lg bg-emerald-500/10 border border-emerald-500/30 text-emerald-400 text-xs font-mono animate-in fade-in duration-300 max-w-[600px] truncate">
            <span className="relative flex h-2 w-2 flex-shrink-0">
              <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-emerald-400 opacity-75"></span>
              <span className="relative inline-flex rounded-full h-2 w-2 bg-emerald-500"></span>
            </span>
            <span className="font-semibold text-emerald-300 flex-shrink-0">LIVE:</span>
            <span className="px-1.5 py-0.5 rounded bg-emerald-500/20 text-emerald-200 font-bold flex-shrink-0">
              {latestLiveRequest.cache?.layer ? `${latestLiveRequest.cache.layer} ${latestLiveRequest.cache.status}` : (latestLiveRequest.cacheLayer || latestLiveRequest.status || 'OK')}
            </span>
            <span className="text-text-secondary truncate">
              "{latestLiveRequest.prompt || latestLiveRequest.query || latestLiveRequest.requestBody?.query || 'request'}"
            </span>
            <span className="text-text-muted flex-shrink-0">({latestLiveRequest.latency}ms)</span>
          </div>
        )}
      </div>

      <div className="flex items-center gap-4 px-6">
        {/* Environment Selector */}
        <div className="relative" style={{ zIndex: 20 }}>
          <Button
            variant="ghost"
            size="sm"
            className="gap-1.5"
            onClick={() => {}}
          >
            {environments.find(e => e.value === environment)?.icon}
            <span className="text-body font-medium">{environments.find(e => e.value === environment)?.label}</span>
          </Button>
        </div>

        {/* Connection Status */}
        <div className="flex items-center gap-1.5 px-3 py-1 rounded-full bg-bg-elevated border border-border-subtle">
          <span className={cn('w-2 h-2 rounded-full', connected ? 'bg-success' : 'bg-error')} />
          <span className="text-metadata font-medium">{connected ? 'Connected' : 'Offline'}</span>
        </div>

        {/* Theme Toggle */}
        <Button
          variant="ghost"
          size="sm"
          onClick={() => setTheme(theme === 'dark' ? 'light' : 'dark')}
          aria-label={theme === 'dark' ? 'Switch to light mode' : 'Switch to dark mode'}
        >
          {theme === 'dark' ? <Sun className="w-4 h-4" /> : <Moon className="w-4 h-4" />}
        </Button>

        {/* User Menu */}
        <div className="relative">
          <Button variant="ghost" size="sm" className="gap-1.5 pr-2 pl-3">
            <div className="w-8 h-8 rounded-full bg-accent/20 flex items-center justify-center">
              <Zap className="w-4 h-4 text-accent" />
            </div>
          </Button>
        </div>

        {actions}
      </div>
    </header>
  )
}

// PageContainer component
interface PageContainerProps {
  children: React.ReactNode
  className?: string
}

export function PageContainer({ children, className }: PageContainerProps) {
  return (
    <div className={cn('flex min-h-screen', className)}>
      <Sidebar />
      <div className="flex-1 flex flex-col min-w-0 ml-[248px]">
        <Header />
        <main className="flex-1 overflow-y-auto p-6 max-w-[1600px] mx-auto w-full">
          {children}
        </main>
      </div>
    </div>
  )
}

// AppLayout - main layout wrapper
export function AppLayout() {
  return (
    <PageContainer>
      <Outlet />
    </PageContainer>
  )
}

// Protected route wrapper
interface ProtectedRouteProps {
  children: React.ReactNode
  requiredEnv?: ('development' | 'staging' | 'production')[]
}

export function ProtectedRoute({ children, requiredEnv }: ProtectedRouteProps) {
  const { environment } = useUIStore()

  if (requiredEnv && !requiredEnv.includes(environment)) {
    return <Navigate to="/" replace />
  }

  return <>{children}</>
}