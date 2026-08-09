import { ServiceHealthPanel } from "@/components/dashboard/service-health-panel"

export const metadata = {
  title: "Service Health — JAWARA",
}

export default function ServiceHealthPage() {
  return (
    <div className="flex max-w-2xl flex-col gap-6">
      <header>
        <h1 className="text-xl font-semibold tracking-tight">Service Health</h1>
        <p className="text-sm text-muted-foreground">
          Ketersediaan dasar tiap service: apakah service-nya jalan sekarang. Tren CPU/RAM/disk berada di
          luar cakupan.
        </p>
      </header>

      <ServiceHealthPanel intervalMs={10000} />
    </div>
  )
}
