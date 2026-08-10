"use client"

import * as React from "react"

import { api, GatewayError, type ActivityItem } from "@/lib/api"

const MAX_ITEMS = 50
const RECONNECT_DELAY_MS = 3000

/**
 * Live Activity: one seed fetch for the initial list, then an SSE connection
 * that prepends every new event as it arrives.
 *
 * The reconnect loop is deliberately unconditional (network blip, gateway
 * restart, idle proxy timeout all look the same from here) rather than
 * classifying the failure — a live feed that silently stops updating is a
 * worse failure mode than one that retries every disconnect, including ones
 * it did not need to.
 */
export function useActivityStream(seedLimit = 25) {
  const [items, setItems] = React.useState<ActivityItem[]>([])
  const [connected, setConnected] = React.useState(false)
  const [error, setError] = React.useState<string | null>(null)
  const [loading, setLoading] = React.useState(true)

  React.useEffect(() => {
    let cancelled = false
    const controller = new AbortController()

    async function seed() {
      try {
        const result = await api.activity(seedLimit, controller.signal)
        if (cancelled) return
        if (result.available) {
          setItems(result.items)
          setError(null)
        } else {
          setError(result.reason ?? "tidak tersedia")
        }
      } catch (caught) {
        if (!cancelled) setError(caught instanceof GatewayError ? caught.message : "gagal memuat")
      } finally {
        if (!cancelled) setLoading(false)
      }
    }

    async function connect() {
      while (!cancelled) {
        try {
          setConnected(true)
          await api.streamActivity((item) => {
            if (cancelled) return
            setItems((current) => [item, ...current].slice(0, MAX_ITEMS))
            setError(null)
          }, controller.signal)
        } catch (caught) {
          if (cancelled) return
          setError(caught instanceof GatewayError ? caught.message : "koneksi live terputus")
        }
        setConnected(false)
        if (cancelled) return
        await new Promise((resolve) => setTimeout(resolve, RECONNECT_DELAY_MS))
      }
    }

    void seed()
    void connect()

    return () => {
      cancelled = true
      controller.abort()
    }
  }, [seedLimit])

  return { items, connected, error, loading }
}
