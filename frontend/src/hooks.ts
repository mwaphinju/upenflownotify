import { useEffect, useRef, useState } from 'react'
import { api } from './api'
import type { Configuration, SenderIds } from './types'

/** Re-runs `callback` on an interval (and immediately whenever the tab becomes visible again,
 * so data doesn't sit stale while the tab was backgrounded) without re-arming the timer on every
 * render — always calls the latest `callback` via a ref, so pages don't need `useCallback`. */
export function useAutoRefresh(callback: () => void, intervalMs: number) {
  const callbackRef = useRef(callback)
  useEffect(() => { callbackRef.current = callback })
  useEffect(() => {
    function tick() {
      if (document.visibilityState === 'visible') callbackRef.current()
    }
    const timer = window.setInterval(tick, intervalMs)
    document.addEventListener('visibilitychange', tick)
    return () => {
      window.clearInterval(timer)
      document.removeEventListener('visibilitychange', tick)
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [intervalMs])
}

export function useSenderIds(): SenderIds | null {
  const [value, setValue] = useState<SenderIds | null>(null)
  useEffect(() => { api<SenderIds>('/api/settings/sender-ids').then(setValue).catch(() => undefined) }, [])
  return value
}

export function useConfigSlice<T>(select: (config: Configuration) => T) {
  const [value, setValue] = useState<T | null>(null)
  const [error, setError] = useState('')
  const [loading, setLoading] = useState(true)
  useEffect(() => {
    api<Configuration>('/api/settings').then((config) => setValue(select(config))).catch((reason) => setError(reason instanceof Error ? reason.message : 'Unable to load settings.')).finally(() => setLoading(false))
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])
  return { value, setValue, error, setError, loading }
}
