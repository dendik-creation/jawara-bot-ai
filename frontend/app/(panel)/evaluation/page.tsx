import { ModelEvaluationList } from "@/components/dashboard/model-evaluation-list"
import { PageTitle } from "@/components/page/page-title"

export default function EvaluationPage() {
  return (
    <div className="flex flex-col gap-6">
      <PageTitle
        title="Evaluation"
        description="Gerbang antara model selesai dilatih dan model boleh melayani produksi — butuh training job COMPLETED (06_Model_Evaluation, Planned)."
      />

      <ModelEvaluationList />
    </div>
  )
}
