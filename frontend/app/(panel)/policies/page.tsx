import { PolicyList } from "@/components/dashboard/policy-list"
import { PageTitle } from "@/components/page/page-title"

export default function PoliciesPage() {
  return (
    <div className="flex flex-col gap-6">
      <PageTitle
        title="Security Policies"
        description="Konfigurasi respons IF/THEN — allowlist/blocklist (Detection Rules) → user spesifik → kategori+threshold → default."
      />

      <PolicyList />
    </div>
  )
}
