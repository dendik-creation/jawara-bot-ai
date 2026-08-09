import type { Metadata } from "next"

import { LoginForm } from "@/components/auth/login-form"

export const metadata: Metadata = {
  title: "Masuk — JAWARA Control Panel",
}

export default function LoginPage() {
  return (
    <main className="flex min-h-svh items-center justify-center px-4 py-10">
      <LoginForm />
    </main>
  )
}
