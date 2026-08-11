import { ModelVersionList } from "@/components/dashboard/model-version-list"
import { PageTitle } from "@/components/page/page-title"

export default function ModelsPage() {
  return (
    <div className="flex flex-col gap-6">
      <PageTitle
        title="Models"
        description="Lifecycle CANDIDATE → VALIDATED → PRODUCTION → ARCHIVED — baris muncul otomatis begitu evaluasi selesai (07_Model_Registry_and_Deployment, Planned)."
      />

      <ModelVersionList />
    </div>
  )
}
