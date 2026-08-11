"use client"

import { api, type RecentPanels as RecentPanelsData } from "@/lib/api"
import { usePolling } from "@/hooks/use-polling"
import { Badge, riskVariant } from "@/components/ui/badge"
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card"

/** Recent threats / incidents / alerts — all three have real tables now. */
function alertSeverityVariant(severity: "LOW" | "MEDIUM" | "HIGH" | "CRITICAL"): "high" | "medium" | "low" {
  if (severity === "CRITICAL" || severity === "HIGH") return "high"
  if (severity === "MEDIUM") return "medium"
  return "low"
}

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

      <Card>
        <CardHeader>
          <CardTitle>Recent Incidents</CardTitle>
          <CardDescription>Unit investigasi terbaru.</CardDescription>
        </CardHeader>
        <CardContent>
          {error || !data?.incidents?.available ? (
            <p className="text-sm text-muted-foreground">
              Belum tersedia{data?.incidents?.reason ? ` (${data.incidents.reason})` : ""}.
            </p>
          ) : data.incidents.items.length === 0 ? (
            <p className="text-sm text-muted-foreground">Belum ada incident.</p>
          ) : (
            <ul className="flex flex-col gap-2">
              {data.incidents.items.map((incident) => (
                <li key={incident.id} className="flex items-center justify-between gap-2 text-sm">
                  <div className="flex min-w-0 flex-col">
                    <span className="truncate">{incident.title}</span>
                    <span className="truncate text-xs text-muted-foreground">
                      {incident.code} · {incident.state}
                    </span>
                  </div>
                  <Badge variant={alertSeverityVariant(incident.severity)}>{incident.severity}</Badge>
                </li>
              ))}
            </ul>
          )}
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle>Recent Alerts</CardTitle>
          <CardDescription>Notifikasi terbaru yang butuh perhatian operator.</CardDescription>
        </CardHeader>
        <CardContent>
          {error || !data?.alerts?.available ? (
            <p className="text-sm text-muted-foreground">
              Belum tersedia{data?.alerts?.reason ? ` (${data.alerts.reason})` : ""}.
            </p>
          ) : data.alerts.items.length === 0 ? (
            <p className="text-sm text-muted-foreground">Belum ada alert.</p>
          ) : (
            <ul className="flex flex-col gap-2">
              {data.alerts.items.map((alert) => (
                <li key={alert.id} className="flex items-center justify-between gap-2 text-sm">
                  <div className="flex min-w-0 flex-col">
                    <span className="truncate">{alert.title}</span>
                    <span className="truncate text-xs text-muted-foreground">{alert.state}</span>
                  </div>
                  <Badge variant={alertSeverityVariant(alert.severity)}>{alert.severity}</Badge>
                </li>
              ))}
            </ul>
          )}
        </CardContent>
      </Card>
    </div>
  )
}
