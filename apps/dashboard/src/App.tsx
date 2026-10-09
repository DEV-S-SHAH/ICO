// Main App Component with Routing

import React, { useEffect } from 'react'
import { Routes, Route, Navigate, useLocation } from 'react-router-dom'
import { AppLayout } from './components/layout'
import {
  Overview,
  Requests,
  RequestDetailDrawer,
  Cache,
  Models,
  Providers,
  Costs,
  Analytics,
  Playground,
  Settings,
  Endpoints,
  ApiKeys,
  Configuration,
  Docs,
  Webhooks,
  Logs,
  Status,
} from './pages'
import { useUIStore, useDataStore } from './lib/stores'
import { getApiClient } from './lib/api/client'

function ProtectedRoute({ children }: { children: React.ReactNode }) {
  // In a real app, you'd check auth here. Errors are contained per-route so a
  // single page failure never blanks the whole dashboard.
  return <ErrorBoundary>{children}</ErrorBoundary>
}

class ErrorBoundary extends React.Component<{ children: React.ReactNode }, { hasError: boolean }> {
  constructor(props: { children: React.ReactNode }) {
    super(props)
    this.state = { hasError: false }
  }

  static getDerivedStateFromError() {
    return { hasError: true }
  }

  render() {
    if (this.state.hasError) {
      return (
        <div className="flex flex-col items-center justify-center min-h-[50vh] gap-4 text-center">
          <p className="text-body text-text-secondary">This page failed to load.</p>
          <button
            onClick={() => window.location.reload()}
            className="px-4 py-2 rounded-lg bg-accent/10 text-accent font-medium hover:bg-accent/20 transition-colors"
          >
            Reload
          </button>
        </div>
      )
    }
    return this.props.children
  }
}

function RealTimeSync() {
  const { setConnected, bumpLiveTick } = useUIStore()

  useEffect(() => {
    const api = getApiClient()
    let ws: WebSocket | null = null
    let wsOpen = false
    let closed = false
    let reconnectTimer: ReturnType<typeof setTimeout> | null = null
    let lastEventAt = Date.now()

    const markEvent = () => { lastEventAt = Date.now() }

    async function checkHealth() {
      try {
        const health = await api.healthCheck()
        setConnected(health.status === 'ok')
      } catch {
        setConnected(false)
      }
    }

    function connect() {
      const wsUrl = import.meta.env.VITE_WS_URL || 'ws://localhost:8000/ws'
      try {
        ws = new WebSocket(wsUrl)
        ws.onopen = () => { wsOpen = true; setConnected(true); markEvent(); bumpLiveTick() }
        ws.onmessage = (event) => {
          try {
            const parsed = JSON.parse(event.data)
            if (parsed.type === 'RequestCompleted' && parsed.payload) {
              markEvent()
              useUIStore.getState().setLatestLiveRequest(parsed.payload)
              const dataStore = useDataStore.getState()
              const updated = [
                parsed.payload,
                ...dataStore.requests.filter((r) => r.id !== parsed.payload.id),
              ]
              dataStore.setRequests(updated)
              bumpLiveTick()
            } else if (['CacheInvalidation', 'CacheHit', 'CacheMiss'].includes(parsed.type)) {
              markEvent()
              bumpLiveTick()
            }
          } catch { /* ignore malformed */ }
        }
        ws.onclose = () => {
          wsOpen = false
          if (!closed) reconnectTimer = setTimeout(connect, 3000)
        }
      } catch {
        reconnectTimer = setTimeout(connect, 3000)
      }
    }

    checkHealth()
    connect()
    // Health every 5s; if the WebSocket is down OR no event arrived recently,
    // bump liveTick so every page silently re-syncs from the REST API. This
    // keeps all pages seamless even if the WS connection stalls or dies.
    const timer = setInterval(() => {
      checkHealth()
      if (!wsOpen || Date.now() - lastEventAt > 12000) bumpLiveTick()
    }, 5000)

    return () => {
      closed = true
      clearInterval(timer)
      if (reconnectTimer) clearTimeout(reconnectTimer)
      ws?.close()
    }
  }, [setConnected, bumpLiveTick])

  return null
}

function AppRoutes() {
  const location = useLocation()
  const { requestDetailId, closeRequestDetail } = useUIStore()

  // Close drawer on route change
  useEffect(() => {
    if (requestDetailId) closeRequestDetail()
  }, [location.pathname, requestDetailId, closeRequestDetail])

  // Get the request detail data from data store
  const { requests } = useDataStore()
  const requestDetail = requests.find((r) => r.id === requestDetailId)

  return (
    <>
      <RealTimeSync />
      <Routes>
      <Route path="/" element={<AppLayout />}>
        <Route index element={<ProtectedRoute><Overview /></ProtectedRoute>} />
        <Route path="requests" element={<ProtectedRoute><Requests /></ProtectedRoute>} />
        <Route path="cache" element={<ProtectedRoute><Cache /></ProtectedRoute>} />
        <Route path="models" element={<ProtectedRoute><Models /></ProtectedRoute>} />
        <Route path="providers" element={<ProtectedRoute><Providers /></ProtectedRoute>} />
        <Route path="costs" element={<ProtectedRoute><Costs /></ProtectedRoute>} />
        <Route path="analytics" element={<ProtectedRoute><Analytics /></ProtectedRoute>} />
        <Route path="playground" element={<ProtectedRoute><Playground /></ProtectedRoute>} />
        <Route path="settings" element={<ProtectedRoute><Settings /></ProtectedRoute>} />
        <Route path="endpoints" element={<ProtectedRoute><Endpoints /></ProtectedRoute>} />
        <Route path="api-keys" element={<ProtectedRoute><ApiKeys /></ProtectedRoute>} />
        <Route path="configuration" element={<ProtectedRoute><Configuration /></ProtectedRoute>} />
        <Route path="docs" element={<ProtectedRoute><Docs /></ProtectedRoute>} />
        <Route path="webhooks" element={<ProtectedRoute><Webhooks /></ProtectedRoute>} />
        <Route path="logs" element={<ProtectedRoute><Logs /></ProtectedRoute>} />
        <Route path="status" element={<ProtectedRoute><Status /></ProtectedRoute>} />
      </Route>
      <Route path="*" element={<Navigate to="/" replace />} />
    </Routes>
      <RequestDetailDrawer request={requestDetail || null} open={!!requestDetailId} onClose={closeRequestDetail} />
    </>
  )
}

// Pre-warm caches in the background without blocking the UI. Pages render
// immediately with their own loading states.
function AppInitializer() {
  const { setConnected } = useUIStore()

  useEffect(() => {
    const api = getApiClient()
    Promise.allSettled([
      api.healthCheck(),
      api.getOverviewMetrics(),
      api.getModels(),
      api.getProviders(),
      api.getCacheMetrics(),
    ]).then((results) => {
      const health = results[0]
      if (health.status === 'fulfilled' && health.value?.status === 'ok') {
        setConnected(true)
      }
    })
  }, [setConnected])

  return <AppRoutes />
}

function App() {
  return <AppInitializer />
}

export default App