import { UserDetail } from "@/components/dashboard/user-detail"
import { PageTitle } from "@/components/page/page-title"

export default async function UserDetailPage({ params }: { params: Promise<{ user_hash: string }> }) {
  const { user_hash: userHash } = await params

  return (
    <div className="flex flex-col gap-6">
      <PageTitle title="User Detail" description="Risk profile, riwayat threat, dan status blokir." back />

      <UserDetail userHash={userHash} />
    </div>
  )
}
