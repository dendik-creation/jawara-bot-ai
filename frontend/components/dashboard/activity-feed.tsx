"use client"

import { api, type ActivityFeed as ActivityFeedData } from "@/lib/api"
import { usePolling } from "@/hooks/use-polling"
import { Badge, riskVariant } from "@/components/ui/badge"
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card"

/**
 * Live Activity.
 *
 * Metadata and classification only — never message content
 * (08_Dashboard/02_Command_Center.md §3, privacy note). The gateway does not
 * send `extracted_text` to this endpoint at all, so there is nothing here to
 * leak by accident.
 */
export function ActivityFeed({ limit = 15, intervalMs = 10000 }: { limit?: number; intervalMs?: number }) {
  const { data, error, loading } = usePolling<ActivityFeedData>(
    (signal) => api.activity(limit, signal),
    intervalMs,
  )

  return (
    <Card>
      <CardHeader>
        <CardTitle>Live Activity</CardTitle>
        <CardDescription>
          Event keamanan terbaru. Transport sementara: polling tiap {Math.round(intervalMs / 1000)} detik.
        </CardDescription>
      </CardHeader>
      <CardContent>
        {error ? (
          <p className="text-sm text-muted-foreground">Gateway tidak dapat dihubungi.</p>
        ) : loading && !data ? (
          <p className="text-sm text-muted-foreground">Memuat…</p>
        ) : !data?.available ? (
          <p className="text-sm text-muted-foreground">Belum tersedia ({data?.reason ?? "tidak diketahui"}).</p>
        ) : data.items.length === 0 ? (
          <p className="text-sm text-muted-foreground">Belum ada pesan yang diproses.</p>
        ) : (
          <ul className="flex flex-col divide-y divide-border">
            {data.items.map((item) => (
              <li key={item.id} className="flex flex-wrap items-center gap-2 py-2 text-sm">
                <span className="font-mono text-xs text-muted-foreground tabular-nums">
                  {new Date(item.at).toLocaleTimeString("id-ID")}
                </span>
                <span className="font-medium">{item.event}</span>
                <Badge variant={riskVariant(item.risk)}>{item.risk}</Badge>
                <Badge variant="outline">{item.intent ?? "UNCLASSIFIED"}</Badge>
                <span className="text-xs text-muted-foreground">
                  {item.chat_type} · {item.input_type}
                  {item.latency_ms !== null ? ` · ${item.latency_ms} ms` : ""}
                </span>
              </li>
            ))}
          </ul>
        )}
      </CardContent>
    </Card>
  )
}
