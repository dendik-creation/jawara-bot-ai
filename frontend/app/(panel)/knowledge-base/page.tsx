import { KnowledgeBaseList } from "@/components/dashboard/knowledge-base-list"
import { PageTitle } from "@/components/page/page-title"

export default function KnowledgeBasePage() {
  return (
    <div className="flex flex-col gap-6">
      <PageTitle
        title="Knowledge Base"
        description="Fact items yang di-embed ke Qdrant lewat ML Service — dasar retrieval untuk verifikasi klaim."
      />

      <KnowledgeBaseList />
    </div>
  )
}
