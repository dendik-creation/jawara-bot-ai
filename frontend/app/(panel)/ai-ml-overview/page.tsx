import { AiMlOverviewGrid } from "@/components/dashboard/ai-ml-overview"
import { PageTitle } from "@/components/page/page-title"

export default function AiMlOverviewPage() {
  return (
    <div className="flex flex-col gap-6">
      <PageTitle
        title="AI/ML Overview"
        description="Ringkasan Knowledge Base, Detection Rules, Policies, dan status ML Service — bukan analitik infrastruktur time-series."
      />

      <AiMlOverviewGrid />
    </div>
  )
}
