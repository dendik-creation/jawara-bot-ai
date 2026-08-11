import { ServiceHealthPanel } from "@/components/dashboard/service-health-panel"
import { PageTitle } from "@/components/page/page-title"

export default function ServiceHealthPage() {
  return (
    <div className="flex flex-col gap-6">
      <PageTitle
        title="Service Health"
        description="Ketersediaan dasar tiap service: apakah service-nya jalan sekarang. Tren CPU/RAM/disk berada di luar cakupan."
      />

      <ServiceHealthPanel intervalMs={10000} showHeader={false} />
    </div>
  )
}
