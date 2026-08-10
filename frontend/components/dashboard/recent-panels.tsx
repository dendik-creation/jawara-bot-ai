"use client"

import { api, type RecentPanels as RecentPanelsData } from "@/lib/api"
import { usePolling } from "@/hooks/use-polling"
import { Badge, riskVariant } from "@/components/ui/badge"
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card"

/**
 * Recent threats / incidents / alerts.
 *
 * Incidents and alerts have no tables yet, so they say so. An empty list would
 * be read as "nothing happened", which is a different — and false — claim.
 */
export function RecentPanels({ intervalMs = 20000 }: { intervalMs?: number }) {
  const { data, error } = usePolling<RecentPanelsData>(api.recent, intervalMs)

  return (
    <div className="grid gap-4 md:grid-cols-3">
      <Card>
        <CardHeader>
          <CardTitle>Recent Threats</CardTitle>
          <CardDescription>Ancaman terbaru (HIGH / MEDIUM).</CardDescription>
        </CardHeader>
        <CardContent>
          {error || !data?.threats?.available ? (
            <p className="text-sm text-muted-foreground">
              Belum tersedia{data?.threats?.reason ? ` (${data.threats.reason})` : ""}.
            </p>
          ) : data.threats.items.length === 0 ? (
            <p className="text-sm text-muted-foreground">Belum ada ancaman terdeteksi.</p>
          ) : (
            <ul className="flex flex-col gap-2">
              {data.threats.items.map((threat) => (
                <li key={threat.id} className="flex items-center justify-between gap-2 text-sm">
                  <div className="flex min-w-0 flex-col">
                    <span className="truncate">{threat.intent ?? "UNCLASSIFIED"}</span>
                    <span className="truncate text-xs text-muted-foreground">{threat.threat_category}</span>
                  </div>
                  <Badge variant={riskVariant(threat.risk)}>{threat.risk}</Badge>
                </li>
              ))}
            </ul>
          )}
        </CardContent>
      </Card>

      <UnavailableCard
        title="Recent Incidents"
        description="Incident Management belum diimplementasikan."
        reason={data?.incidents?.reason}
      />
      <UnavailableCard
        title="Recent Alerts"
        description="Alert Center belum diimplementasikan."
        reason={data?.alerts?.reason}
      />
    </div>
  )
}

function UnavailableCard({
  title,
  description,
  reason,
}: {
  title: string
  description: string
  reason?: string
}) {
  return (
    <Card>
      <CardHeader>
        <CardTitle>{title}</CardTitle>
        <CardDescription>{description}</CardDescription>
      </CardHeader>
      <CardContent>
        <Badge variant="outline">belum tersedia</Badge>
        {reason ? <p className="text-xs text-muted-foreground">{reason}</p> : null}
      </CardContent>
    </Card>
  )
}
