import { MessageInspection } from "@/components/dashboard/message-inspection"
import { PageTitle } from "@/components/page/page-title"

export default function MessagesPage() {
  return (
    <div className="flex flex-col gap-6">
      <PageTitle
        title="Messages"
        description="Isi pesan yang sudah dianalisis pipeline, disimpan tanpa retention otomatis."
      />

      <MessageInspection />
    </div>
  )
}
