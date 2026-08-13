import { TrainingJobList } from "@/components/dashboard/training-job-list"
import { PageTitle } from "@/components/page/page-title"

export default function TrainingJobsPage() {
  return (
    <div className="flex flex-col gap-6">
      <PageTitle
        title="Training Jobs"
        description="Operasi asinkron terkontrol atas dataset VALIDATED — memicu training model via ML Service dan melacak status hingga selesai."
      />

      <TrainingJobList />
    </div>
  )
}
