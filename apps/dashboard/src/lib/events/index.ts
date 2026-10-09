// Event system for real-time dashboard updates

import type { DashboardEvent, EventType } from '@/types'

type EventHandler = (event: DashboardEvent) => void
type ConnectionHandler = (connected: boolean) => void
type ErrorHandler = (error: Error) => void

export interface EventProvider {
  connect(): Promise<void>
  disconnect(): void
  on(event: EventType, handler: EventHandler): () => void
  onConnect(handler: ConnectionHandler): () => void
  onError(handler: ErrorHandler): () => void
  isConnected(): boolean
}

class WebSocketEventProvider implements EventProvider {
  private ws: WebSocket | null = null
  private handlers: Map<EventType, Set<EventHandler>> = new Map()
  private connectHandlers: Set<ConnectionHandler> = new Set()
  private errorHandlers: Set<ErrorHandler> = new Set()
  private url: string
  private reconnectAttempts = 0
  private maxReconnectAttempts = 5
  private reconnectDelay = 1000

  constructor(url: string) {
    this.url = url
  }

  async connect(): Promise<void> {
    return new Promise((resolve, reject) => {
      try {
        this.ws = new WebSocket(this.url)

        this.ws.onopen = () => {
          this.reconnectAttempts = 0
          this.connectHandlers.forEach(h => h(true))
          resolve()
        }

        this.ws.onmessage = (event) => {
          try {
            const eventData: DashboardEvent = JSON.parse(event.data)
            this.handlers.get(eventData.type)?.forEach(h => h(eventData))
          } catch (error) {
            console.error('Failed to parse event:', error)
          }
        }

        this.ws.onclose = () => {
          this.connectHandlers.forEach(h => h(false))
          this.attemptReconnect()
        }

        this.ws.onerror = (error) => {
          this.errorHandlers.forEach(h => h(new Error('WebSocket error')))
          reject(new Error('WebSocket connection failed'))
        }
      } catch (error) {
        reject(error)
      }
    })
  }

  private attemptReconnect(): void {
    if (this.reconnectAttempts >= this.maxReconnectAttempts) {
      this.errorHandlers.forEach(h => h(new Error('Max reconnect attempts reached')))
      return
    }

    this.reconnectAttempts++
    setTimeout(() => this.connect(), this.reconnectDelay * this.reconnectAttempts)
  }

  disconnect(): void {
    this.ws?.close()
    this.ws = null
  }

  on(event: EventType, handler: EventHandler): () => void {
    if (!this.handlers.has(event)) {
      this.handlers.set(event, new Set())
    }
    this.handlers.get(event)!.add(handler)
    return () => this.handlers.get(event)?.delete(handler)
  }

  onConnect(handler: ConnectionHandler): () => void {
    this.connectHandlers.add(handler)
    return () => this.connectHandlers.delete(handler)
  }

  onError(handler: ErrorHandler): () => void {
    this.errorHandlers.add(handler)
    return () => this.errorHandlers.delete(handler)
  }

  isConnected(): boolean {
    return this.ws?.readyState === WebSocket.OPEN
  }
}

class SSEEventProvider implements EventProvider {
  private es: EventSource | null = null
  private handlers: Map<EventType, Set<EventHandler>> = new Map()
  private connectHandlers: Set<ConnectionHandler> = new Set()
  private errorHandlers: Set<ErrorHandler> = new Set()
  private url: string

  constructor(url: string) {
    this.url = url
  }

  async connect(): Promise<void> {
    return new Promise((resolve, reject) => {
      try {
        this.es = new EventSource(this.url)

        this.es.onopen = () => {
          this.connectHandlers.forEach(h => h(true))
          resolve()
        }

        this.es.onmessage = (event) => {
          try {
            const eventData: DashboardEvent = JSON.parse(event.data)
            this.handlers.get(eventData.type)?.forEach(h => h(eventData))
          } catch (error) {
            console.error('Failed to parse event:', error)
          }
        }

        this.es.onerror = () => {
          this.connectHandlers.forEach(h => h(false))
          this.errorHandlers.forEach(h => h(new Error('SSE connection error')))
          reject(new Error('SSE connection failed'))
        }
      } catch (error) {
        reject(error)
      }
    })
  }

  disconnect(): void {
    this.es?.close()
    this.es = null
  }

  on(event: EventType, handler: EventHandler): () => void {
    if (!this.handlers.has(event)) {
      this.handlers.set(event, new Set())
    }
    this.handlers.get(event)!.add(handler)
    return () => this.handlers.get(event)?.delete(handler)
  }

  onConnect(handler: ConnectionHandler): () => void {
    this.connectHandlers.add(handler)
    return () => this.connectHandlers.delete(handler)
  }

  onError(handler: ErrorHandler): () => void {
    this.errorHandlers.add(handler)
    return () => this.errorHandlers.delete(handler)
  }

  isConnected(): boolean {
    return this.es?.readyState === EventSource.OPEN
  }
}

class PollingEventProvider implements EventProvider {
  private handlers: Map<EventType, Set<EventHandler>> = new Map()
  private connectHandlers: Set<ConnectionHandler> = new Set()
  private errorHandlers: Set<ErrorHandler> = new Set()
  private intervalId: ReturnType<typeof setInterval> | null = null
  private interval: number
  private apiUrl: string
  private apiKey?: string
  private lastEventId = ''

  constructor(apiUrl: string, apiKey?: string, interval = 5000) {
    this.apiUrl = apiUrl
    this.apiKey = apiKey
    this.interval = interval
  }

  async connect(): Promise<void> {
    this.connectHandlers.forEach(h => h(true))
    this.poll()
    this.intervalId = setInterval(() => this.poll(), this.interval)
  }

  private async poll(): Promise<void> {
    try {
      const headers: Record<string, string> = {}
      if (this.apiKey) {
        headers['X-API-Key'] = this.apiKey
      }
      if (this.lastEventId) {
        headers['Last-Event-ID'] = this.lastEventId
      }

      const response = await fetch(`${this.apiUrl}/v1/events/poll`, { headers })
      if (!response.ok) throw new Error(`HTTP ${response.status}`)

      const events: DashboardEvent[] = await response.json()
      events.forEach(event => {
        this.lastEventId = event.id
        this.handlers.get(event.type)?.forEach(h => h(event))
      })
    } catch (error) {
      this.errorHandlers.forEach(h => h(error instanceof Error ? error : new Error('Polling failed')))
    }
  }

  disconnect(): void {
    if (this.intervalId) {
      clearInterval(this.intervalId)
      this.intervalId = null
    }
    this.connectHandlers.forEach(h => h(false))
  }

  on(event: EventType, handler: EventHandler): () => void {
    if (!this.handlers.has(event)) {
      this.handlers.set(event, new Set())
    }
    this.handlers.get(event)!.add(handler)
    return () => this.handlers.get(event)?.delete(handler)
  }

  onConnect(handler: ConnectionHandler): () => void {
    this.connectHandlers.add(handler)
    return () => this.connectHandlers.delete(handler)
  }

  onError(handler: ErrorHandler): () => void {
    this.errorHandlers.add(handler)
    return () => this.errorHandlers.delete(handler)
  }

  isConnected(): boolean {
    return this.intervalId !== null
  }
}

// Factory function to create the appropriate provider
export function createEventProvider(
  type: 'websocket' | 'sse' | 'polling',
  config: { url?: string; apiKey?: string; interval?: number } = {}
): EventProvider {
  switch (type) {
    case 'websocket':
      return new WebSocketEventProvider(config.url || 'ws://localhost:8000/ws')
    case 'sse':
      return new SSEEventProvider(config.url || 'http://localhost:8000/v1/events')
    case 'polling':
      return new PollingEventProvider(config.url || 'http://localhost:8000', config.apiKey, config.interval)
    default:
      return new WebSocketEventProvider(config.url || 'ws://localhost:8000/ws')
  }
}

// Event bus for internal component communication
class EventBus {
  private handlers: Map<string, Set<(...args: unknown[]) => void>> = new Map()

  on(event: string, handler: (...args: unknown[]) => void): () => void {
    if (!this.handlers.has(event)) {
      this.handlers.set(event, new Set())
    }
    this.handlers.get(event)!.add(handler)
    return () => this.handlers.get(event)?.delete(handler)
  }

  emit(event: string, ...args: unknown[]): void {
    this.handlers.get(event)?.forEach(h => h(...args))
  }

  off(event: string, handler: (...args: unknown[]) => void): void {
    this.handlers.get(event)?.delete(handler)
  }

  clear(): void {
    this.handlers.clear()
  }
}

export const eventBus = new EventBus()

// React hook for using events
import { useEffect, useRef, useState } from 'react'

export function useEventProvider(
  type: 'websocket' | 'sse' | 'polling',
  config?: { url?: string; apiKey?: string; interval?: number }
): EventProvider {
  const providerRef = useRef<EventProvider | null>(null)

  if (!providerRef.current) {
    providerRef.current = createEventProvider(type, config)
  }

  return providerRef.current
}

export function useEvent<T extends DashboardEvent>(
  provider: EventProvider | null,
  eventType: T['type'],
  handler: (event: T) => void
): void {
  const handlerRef = useRef(handler)
  handlerRef.current = handler

  useEffect(() => {
    if (!provider) return
    const unsubscribe = provider.on(eventType, (event) => {
      handlerRef.current(event as T)
    })
    return unsubscribe
  }, [provider, eventType])
}

export function useConnectionStatus(provider: EventProvider | null): boolean {
  const [connected, setConnected] = useState(false)

  useEffect(() => {
    if (!provider) return
    const unsubscribe = provider.onConnect(setConnected)
    setConnected(provider.isConnected())
    return unsubscribe
  }, [provider])

  return connected
}