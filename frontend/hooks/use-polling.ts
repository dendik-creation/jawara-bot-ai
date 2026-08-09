"use client"

import * as React from "react"

/**
 * Poll a gateway endpoint on an interval.
 *
 * Polling is a deliberate placeholder: the live-activity transport
 * (SSE / WebSocket / polling) is still an open decision
 * (08_Dashboard/02_Command_Center.md §4), and polling is the only option that
 * needs no extra Redis pub/sub channel. Swapping it later means replacing this
 * hook, not the screens.
 *
 * The previous value is kept while a refresh is in flight, so a slow or failing
 * poll never blanks a dashboard an operator is reading.
 */
export function usePolling<T>(
  fetcher: (signal: AbortSignal) => Promise<T>,
  intervalMs = 15000,
): { data: T | null; error: string | null; loading: boolean; refreshedAt: Date | null } {
  const [data, setData] = React.useState<T | null>(null)
  const [error, setError] = React.useState<string | null>(null)
  const [loading, setLoading] = React.useState(true)
  const [refreshedAt, setRefreshedAt] = React.useState<Date | null>(null)

  // The fetcher is usually an inline closure, so it changes identity on every
  // render. Keeping it in a ref lets the interval below depend only on
  // `intervalMs` — otherwise every render would tear down and restart the timer,
  // and a screen that re-renders often would never actually poll.
  const fetcherRef = React.useRef(fetcher)
  React.useEffect(() => {
    fetcherRef.current = fetcher
  })

  React.useEffect(() => {
    let cancelled = false
    const controller = new AbortController()

    async function load() {
      try {
        const result = await fetcherRef.current(controller.signal)
        if (cancelled) return
        setData(result)
        setError(null)
        setRefreshedAt(new Date())
      } catch (caught) {
        if (cancelled || controller.signal.aborted) return
        setError(caught instanceof Error ? caught.message : "gagal memuat data")
      } finally {
        if (!cancelled) setLoading(false)
      }
    }

    load()
    const timer = setInterval(load, intervalMs)

    return () => {
      cancelled = true
      controller.abort()
      clearInterval(timer)
    }
  }, [intervalMs])

  return { data, error, loading, refreshedAt }
}
