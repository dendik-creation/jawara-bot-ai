import { MessageInspection } from "@/components/dashboard/message-inspection"

export const metadata = {
  title: "Messages — JAWARA",
}

export default function MessagesPage() {
  return (
    <div className="flex max-w-3xl flex-col gap-6">
      <header>
        <h1 className="text-xl font-semibold tracking-tight">Messages</h1>
        <p className="text-sm text-muted-foreground">
          Isi pesan yang sudah dianalisis pipeline, disimpan tanpa retention otomatis.
        </p>
      </header>

      <MessageInspection />
    </div>
  )
}
