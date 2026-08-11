"use client"

import { api, type DashboardSummary, type WhatsAppSessions } from "@/lib/api"
import { usePolling } from "@/hooks/use-polling"
import { ActivityFeed } from "@/components/dashboard/activity-feed"
import { RecentPanels } from "@/components/dashboard/recent-panels"
import { ServiceHealthPanel } from "@/components/dashboard/service-health-panel"
import { StatTile } from "@/components/dashboard/stat-tile"
import { PageTitle } from "@/components/page/page-title"

/**
 * Command Center — the operator's "what is happening right now" screen.
 *
 * A Control & Monitoring Center, not an analytics dashboard: volume, severity,
 * population, recent items, and system health (08_Dashboard/02_Command_Center.md
 * §1). Everything comes from the gateway; nothing here reads a datastore
 * directly.
 */
export function CommandCenter() {
  const { data: summary, error, refreshedAt } = usePolling<DashboardSummary>(api.summary, 15000)
  const { data: sessions } = usePolling<WhatsAppSessions>(api.sessions, 30000)

  const available = summary?.available ?? false
  const value = <K extends keyof DashboardSummary>(key: K) =>
    available ? ((summary?.[key] ?? null) as DashboardSummary[K] | null) : null

  return (
    <div className="flex flex-col gap-6">
      <div className="flex flex-wrap items-end justify-between gap-2">
        <PageTitle
          title="Command Center"
          description={`Ringkasan keamanan operasional ${summary?.window_hours ?? 24} jam terakhir.`}
        />
        <p className="mb-6 text-xs text-muted-foreground">
          {error
            ? "Gateway tidak dapat dihubungi"
            : refreshedAt
              ? `Diperbarui ${refreshedAt.toLocaleTimeString("id-ID")}`
              : "Memuat…"}
        </p>
      </div>

      {!available && !error ? (
        <p className="rounded-lg border border-border bg-muted/40 px-3 py-2 text-sm text-muted-foreground">
          Metrik belum tersedia{summary?.reason ? ` (${summary.reason})` : ""}. Angka tidak ditampilkan
          sampai sumber datanya benar-benar ada.
        </p>
      ) : null}

      <section className="grid gap-4 sm:grid-cols-2 xl:grid-cols-5">
        <StatTile label="Messages Processed" value={value("messages_processed")} />
        <StatTile label="Threats Detected" value={value("threats_detected")} />
        <StatTile label="Critical Threats" value={value("critical_threats")} emphasis />
        <StatTile label="Active Users" value={value("active_users")} hint="pengguna ter-hash, bukan identitas" />
        <StatTile
          label="Active WA Sessions"
          value={sessions?.available ? sessions.active : null}
          hint={sessions?.available ? undefined : "WAHA belum dapat dihubungi"}
        />
      </section>

      <section className="grid gap-4 lg:grid-cols-3">
        <div className="lg:col-span-2">
          <ActivityFeed />
        </div>
        <ServiceHealthPanel />
      </section>

      <RecentPanels />

      <p className="text-xs text-muted-foreground">
        Dashboard hanya menampilkan data agregat dan metadata. Isi pesan (`extracted_text`) tidak pernah
        dikirim ke layar ini.
      </p>
    </div>
  )
}
