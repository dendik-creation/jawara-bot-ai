"use client"

import { useRouter } from "next/navigation"
import * as React from "react"

import { toast } from "@/components/ui/toast"
import { api, UnauthorizedError, type Operator } from "@/lib/api"
import { clearToken, getToken, setToken, subscribe } from "@/lib/session"

type AuthState = {
  operator: Operator | null
  /** True until the stored token has been checked against the gateway. */
  loading: boolean
  signIn: (email: string, password: string) => Promise<void>
  signOut: () => Promise<void>
  /** Applies a fresh operator record (e.g. after a profile edit) without a full reload. */
  updateOperator: (operator: Operator) => void
}

const AuthContext = React.createContext<AuthState | null>(null)

export function useAuth(): AuthState {
  const context = React.useContext(AuthContext)
  if (!context) throw new Error("useAuth must be used inside <AuthProvider>")
  return context
}

export function AuthProvider({ children }: { children: React.ReactNode }) {
  const router = useRouter()
  const [operator, setOperator] = React.useState<Operator | null>(null)
  const [loading, setLoading] = React.useState(true)

  // A token in localStorage proves nothing — it may be expired or revoked. The
  // gateway is asked once on load, and the answer is what the UI trusts.
  React.useEffect(() => {
    const controller = new AbortController()

    async function restore() {
      if (!getToken()) {
        setOperator(null)
        setLoading(false)
        return
      }
      try {
        setOperator(await api.me(controller.signal))
      } catch (error) {
        if (controller.signal.aborted) return
        if (error instanceof UnauthorizedError) clearToken()
        setOperator(null)
      } finally {
        if (!controller.signal.aborted) setLoading(false)
      }
    }

    restore()
    return () => controller.abort()
  }, [])

  // The API client clears the token when any request comes back 401, including
  // a background poll. Without this subscription the screen would keep showing
  // a signed-in shell over data that no longer loads.
  React.useEffect(
    () =>
      subscribe(() => {
        if (!getToken()) {
          setOperator(null)
          router.replace("/login")
        }
      }),
    [router],
  )

  const signIn = React.useCallback(async (email: string, password: string) => {
    const result = await api.login(email, password)
    setToken(result.access_token)
    setOperator(result.operator)
  }, [])

  const signOut = React.useCallback(async () => {
    try {
      // Best effort: the server-side revocation matters, but a network failure
      // must not leave the operator stuck in a session they asked to end.
      await api.logout()
    } catch {
      // ignored on purpose
    }
    clearToken()
    setOperator(null)
    router.replace("/login")
    toast.success("Berhasil keluar", { description: "Sesi kamu sudah diakhiri." })
  }, [router])

  const updateOperator = React.useCallback((next: Operator) => {
    setOperator(next)
  }, [])

  const value = React.useMemo(
    () => ({ operator, loading, signIn, signOut, updateOperator }),
    [operator, loading, signIn, signOut, updateOperator],
  )

  return <AuthContext value={value}>{children}</AuthContext>
}
