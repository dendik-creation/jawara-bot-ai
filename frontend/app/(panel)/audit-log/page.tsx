import { AuditLogList } from "@/components/dashboard/audit-log-list"
import { PageTitle } from "@/components/page/page-title"

export default function AuditLogPage() {
  return (
    <div className="flex flex-col gap-6">
      <PageTitle title="Audit Log" description="Jejak aksi operator: siapa melakukan apa, kapan, dan hasilnya." />

      <AuditLogList />
    </div>
  )
}
