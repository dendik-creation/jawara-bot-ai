"use client"

import { api, type ServiceHealth } from "@/lib/api"
import { usePolling } from "@/hooks/use-polling"
import { Badge } from "@/components/ui/badge"
import { Card, CardHeader, CardTitle, CardDescription, CardContent } from "@/components/ui/card"

/**
 * Basic availability per service — up or down, nothing else.
 *
 * Long-run CPU / RAM / disk trends are Infrastructure Analytics and are
 * Deferred (08_Dashboard/08_Service_Health.md §2). This panel answers "is it
 * running now", which is a different question.
 */
const LABELS: Record<string, string> = {
  api_gateway: "FastAPI Gateway",
  ml_service: "ML Service",
  waha: "WAHA",
  postgres: "PostgreSQL",
  redis: "Redis",
  qdrant: "Qdrant",
}

const ORDER = ["api_gateway", "ml_service", "waha", "postgres", "redis", "qdrant"]

export function ServiceHealthPanel({ intervalMs = 15000 }: { intervalMs?: number }) {
  const { data, error, loading } = usePolling<ServiceHealth>(api.services, intervalMs)

  return (
    <Card>
      <CardHeader>
        <CardTitle>Service Health</CardTitle>
        <CardDescription>
          Ketersediaan dasar tiap service. Bukan analitik infrastruktur.
        </CardDescription>
      </CardHeader>
      <CardContent>
        {error ? (
          <p className="text-sm text-muted-foreground">
            Gateway tidak dapat dihubungi — status service belum tersedia.
          </p>
        ) : loading && !data ? (
          <p className="text-sm text-muted-foreground">Memuat…</p>
        ) : (
          <ul className="flex flex-col gap-2">
            {ORDER.map((key) => {
              const service = data?.services?.[key]
              const status = service?.status
              return (
                <li key={key} className="flex items-center justify-between gap-3 text-sm">
                  <span>{LABELS[key]}</span>
                  <Badge variant={status === "HEALTHY" ? "low" : status === "DOWN" ? "high" : "unknown"}>
                    {status ?? "belum tersedia"}
                  </Badge>
                </li>
              )
            })}
          </ul>
        )}

        {data?.services?.ml_service?.detail &&
        Object.keys(data.services.ml_service.detail).length > 0 ? (
          <p className="text-xs text-muted-foreground">
            ML Service dilaporkan lewat readiness (model sudah dimuat), bukan sekadar liveness.
          </p>
        ) : null}
      </CardContent>
    </Card>
  )
}
