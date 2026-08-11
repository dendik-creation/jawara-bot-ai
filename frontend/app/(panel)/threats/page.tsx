import { ThreatList } from "@/components/dashboard/threat-list"
import { PageTitle } from "@/components/page/page-title"

export default function ThreatsPage() {
  return (
    <div className="flex flex-col gap-6">
      <PageTitle title="Threats" description="Pantau dan triase seluruh ancaman yang terdeteksi platform." />

      <ThreatList />
    </div>
  )
}
