import { AlertList } from "@/components/dashboard/alert-list"
import { PageTitle } from "@/components/page/page-title"

export default function AlertsPage() {
  return (
    <div className="flex flex-col gap-6">
      <PageTitle title="Alerts" description="Pusat pengelolaan alert — notifikasi yang butuh perhatian operator." />

      <AlertList />
    </div>
  )
}
