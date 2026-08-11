import { IncidentDetail } from "@/components/dashboard/incident-detail"
import { PageTitle } from "@/components/page/page-title"

export default async function IncidentDetailPage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params

  return (
    <div className="flex flex-col gap-6">
      <PageTitle title="Incident Detail" description="Detail unit investigasi, threat terkait, dan catatan." back />

      <IncidentDetail id={id} />
    </div>
  )
}
