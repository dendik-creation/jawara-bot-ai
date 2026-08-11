import { DetectionRuleList } from "@/components/dashboard/detection-rule-list"
import { PageTitle } from "@/components/page/page-title"

export default function DetectionRulesPage() {
  return (
    <div className="flex flex-col gap-6">
      <PageTitle
        title="Detection Rules"
        description="Mekanisme deteksi deterministik — keyword, domain, URL, threshold, pattern, allowlist/blocklist."
      />

      <DetectionRuleList />
    </div>
  )
}
