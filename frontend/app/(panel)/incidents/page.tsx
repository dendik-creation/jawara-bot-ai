import { IncidentList } from "@/components/dashboard/incident-list"
import { PageTitle } from "@/components/page/page-title"

export default function IncidentsPage() {
  return (
    <div className="flex flex-col gap-6">
      <PageTitle
        title="Incidents"
        description="Kelompokkan threat yang saling terkait menjadi satu unit investigasi."
      />

      <IncidentList />
    </div>
  )
}
