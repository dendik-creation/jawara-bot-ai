import { UserList } from "@/components/dashboard/user-list"
import { PageTitle } from "@/components/page/page-title"

export default function UsersPage() {
  return (
    <div className="flex flex-col gap-6">
      <PageTitle
        title="Users"
        description="Risk profile, riwayat ancaman, dan blocklist pengguna WhatsApp yang dianalisis."
      />

      <UserList />
    </div>
  )
}
