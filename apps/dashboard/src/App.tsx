// Main App Component with Routing

import React, { useEffect, useState } from 'react'
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
  // In a real app, you'd check auth here
  return <>{children}</>
}

function RealTimeSync() {
  const { demoMode, setConnected, bumpLiveTick } = useUIStore()

  useEffect(() => {
    if (demoMode) return
    const api = getApiClient(false)
    let ws: WebSocket | null = null
    let wsOpen = false
    let closed = false
    let reconnectTimer: ReturnType<typeof setTimeout> | null = null

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
        ws.onopen = () => { wsOpen = true; setConnected(true); bumpLiveTick() }
        ws.onmessage = (event) => {
          try {
            const parsed = JSON.parse(event.data)
            if (parsed.type === 'RequestCompleted' && parsed.payload) {
              useUIStore.getState().setLatestLiveRequest(parsed.payload)
              const dataStore = useDataStore.getState()
              const updated = [
                parsed.payload,
                ...dataStore.requests.filter((r) => r.id !== parsed.payload.id),
              ]
              dataStore.setRequests(updated)
              bumpLiveTick()
            } else if (['CacheInvalidation', 'CacheHit', 'CacheMiss'].includes(parsed.type)) {
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
    // Health every 5s; if the WebSocket is down, fall back to polling refresh
    const timer = setInterval(() => {
      checkHealth()
      if (!wsOpen) bumpLiveTick()
    }, 5000)

    return () => {
      closed = true
      clearInterval(timer)
      if (reconnectTimer) clearTimeout(reconnectTimer)
      ws?.close()
    }
  }, [demoMode, setConnected, bumpLiveTick])

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

// Initialize demo data on startup
function AppInitializer() {
  const { demoMode, setConnected } = useUIStore()
  const [initialized, setInitialized] = useState(false)

  useEffect(() => {
    async function initialize() {
      try {
        // Pre-load some data in background
        const api = getApiClient(demoMode)
        await Promise.allSettled([
          api.healthCheck(),
          api.getOverviewMetrics(),
          api.getModels(),
          api.getProviders(),
          api.getCacheMetrics(),
        ])
        setConnected(true)
      } catch {
        // Demo mode - use mock data
        setConnected(true)
      }
      setInitialized(true)
    }
    initialize()
  }, [demoMode, setConnected])

  if (!initialized) {
    return (
      <div className="min-h-screen flex items-center justify-center bg-bg-primary">
        <div className="text-center">
          <div className="animate-spin rounded-full h-12 w-12 border-b-2 border-accent mx-auto mb-4" />
          <p className="text-body text-text-secondary">Initializing Synapse...</p>
        </div>
      </div>
    )
  }

  return <AppRoutes />
}

function App() {
  return <AppInitializer />
}

export default App