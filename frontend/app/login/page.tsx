import type { Metadata } from "next"
import Image from "next/image"

import { HealthChatPreview } from "@/components/auth/health-chat-preview"
import { LoginForm } from "@/components/auth/login-form"

export const metadata: Metadata = {
  title: "Masuk — JAWARA Control Panel",
}

export default function LoginPage() {
  return (
    <main className="grid min-h-svh lg:grid-cols-3">
      <div className="flex flex-col items-center col-span-1 justify-center gap-8 px-4 py-10">
        <div className="flex w-full max-w-sm items-center gap-2.5">
          <div className="flex size-8 items-center justify-center overflow-hidden rounded-lg bg-background p-1 ring-1 ring-border">
            <Image src="/icon.png" alt="" width={24} height={24} className="size-full object-contain" priority />
          </div>
          <span className="text-sm font-semibold text-foreground">JAWARA Control Panel</span>
        </div>

        <LoginForm />
      </div>

      <div className="relative col-span-2 hidden overflow-hidden bg-sidebar lg:flex lg:items-center lg:justify-center">
        <div className="absolute -top-24 -right-24 size-96 rounded-full bg-primary/25 blur-3xl" aria-hidden />
        <div className="absolute -bottom-32 -left-16 size-96 rounded-full bg-primary/10 blur-3xl" aria-hidden />
        <div className="relative z-10 px-8">
          <HealthChatPreview />
        </div>
      </div>
    </main>
  )
}
