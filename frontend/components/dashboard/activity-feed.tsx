"use client"

import { useActivityStream } from "@/hooks/use-activity-stream"
import { Badge, riskVariant } from "@/components/ui/badge"
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card"

/**
 * Live Activity.
 *
 * Metadata and classification only — never message content
 * (08_Dashboard/02_Command_Center.md §3, privacy note). The gateway does not
 * send `extracted_text` to this endpoint at all, so there is nothing here to
 * leak by accident.
 *
 * Pushed over SSE (`useActivityStream`), not polled — closed 2026-08-10, see
 * [[Open_Decisions_Carried_Forward]] §2.2.
 */
export function ActivityFeed({ limit = 15 }: { limit?: number }) {
  const { items, connected, error, loading } = useActivityStream(limit)

  return (
    <Card>
      <CardHeader>
        <CardTitle>Live Activity</CardTitle>
        <CardDescription className="flex items-center gap-1.5">
          <span
            className={`inline-block size-1.5 rounded-full ${connected ? "bg-primary" : "bg-muted-foreground/40"}`}
            aria-hidden
          />
          {connected ? "Live" : "Menyambungkan ulang…"}
        </CardDescription>
      </CardHeader>
      <CardContent>
        {error && items.length === 0 ? (
          <p className="text-sm text-muted-foreground">{error}</p>
        ) : loading && items.length === 0 ? (
          <p className="text-sm text-muted-foreground">Memuat…</p>
        ) : items.length === 0 ? (
          <p className="text-sm text-muted-foreground">Belum ada pesan yang diproses.</p>
        ) : (
          <ul className="flex flex-col divide-y divide-border">
            {items.map((item) => (
              <li key={item.id} className="flex flex-wrap items-center gap-2 py-2 text-sm">
                <span className="font-mono text-xs text-muted-foreground tabular-nums">
                  {new Date(item.at).toLocaleTimeString("id-ID")}
                </span>
                <span className="font-medium">{item.event}</span>
                <Badge variant={riskVariant(item.risk)}>{item.risk}</Badge>
                <Badge variant="outline">{item.intent ?? "UNCLASSIFIED"}</Badge>
                <Badge variant="outline">{item.threat_category}</Badge>
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
