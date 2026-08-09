"use client"

import { useRouter } from "next/navigation"
import * as React from "react"

import { useAuth } from "@/components/auth/auth-provider"
import { Skeleton } from "@/components/ui/skeleton"

/**
 * Client-side gate for the Control Panel screens.
 *
 * This is a redirect, not a security boundary — the real one is
 * `require_operator` on the gateway, which every screen's data has to pass
 * through. Nothing renders here before the session check finishes, so a signed
 * out visitor never sees the shell flash before being sent to /login.
 */
export function RequireAuth({ children }: { children: React.ReactNode }) {
  const { operator, loading } = useAuth()
  const router = useRouter()

  React.useEffect(() => {
    if (!loading && !operator) router.replace("/login")
  }, [loading, operator, router])

  if (loading || !operator) {
    return (
      <div className="flex min-h-svh flex-col gap-4 p-8" aria-busy="true">
        <Skeleton className="h-8 w-64" />
        <Skeleton className="h-40 w-full" />
        <Skeleton className="h-40 w-full" />
      </div>
    )
  }

  return <>{children}</>
}
