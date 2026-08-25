import { useEffect, useRef, useCallback } from 'react'

type StreamEvent = { type: string; cases?: Array<{ id: string; state: string; recovered_amount: number | null }> }

export function useLiveStream(onEvent: (event: StreamEvent) => void, enabled = true) {
  const esRef = useRef<EventSource | null>(null)
  const onEventRef = useRef(onEvent)
  onEventRef.current = onEvent

  const connect = useCallback(() => {
    if (esRef.current) esRef.current.close()
    const es = new EventSource('/api/v1/events/stream')
    esRef.current = es
    es.onmessage = (e) => {
      try { onEventRef.current(JSON.parse(e.data)) } catch { /* ignore parse errors */ }
    }
    es.onerror = () => {
      es.close()
      // Reconnect after 3s on error
      setTimeout(() => { if (enabled) connect() }, 3000)
    }
  }, [enabled])

  useEffect(() => {
    if (!enabled) return
    connect()
    return () => { esRef.current?.close() }
  }, [connect, enabled])
}
