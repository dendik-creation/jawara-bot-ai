"use client"

import { useRouter } from "next/navigation"
import * as React from "react"
import { Loader2, ShieldCheck } from "lucide-react"

import { useAuth } from "@/components/auth/auth-provider"
import { Alert, AlertDescription } from "@/components/ui/alert"
import { Button } from "@/components/ui/button"
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { GatewayError } from "@/lib/api"

/**
 * Operator sign-in.
 *
 * There is no "forgot password" and no sign-up link, because neither exists on
 * the gateway: accounts are provisioned with `app.scripts.create_operator`.
 * Offering a link that goes nowhere would be worse than not offering one.
 */
export function LoginForm() {
  const { signIn, operator, loading } = useAuth()
  const router = useRouter()
  const [email, setEmail] = React.useState("")
  const [password, setPassword] = React.useState("")
  const [error, setError] = React.useState<string | null>(null)
  const [submitting, setSubmitting] = React.useState(false)

  // Already signed in (bookmarked /login, or a second tab): go to the panel
  // rather than asking for a password that is not needed.
  React.useEffect(() => {
    if (!loading && operator) router.replace("/")
  }, [loading, operator, router])

  async function onSubmit(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault()
    setSubmitting(true)
    setError(null)
    try {
      await signIn(email, password)
      router.replace("/")
    } catch (caught) {
      // The gateway answers one message for wrong password, unknown address and
      // disabled account. This screen repeats it as-is instead of guessing
      // which one it was.
      setError(
        caught instanceof GatewayError
          ? caught.message
          : "Tidak dapat menghubungi gateway. Coba lagi.",
      )
      setPassword("")
      setSubmitting(false)
    }
  }

  return (
    <Card className="w-full max-w-sm">
      <CardHeader>
        <div className="mb-2 flex size-9 items-center justify-center rounded-lg bg-primary text-primary-foreground">
          <ShieldCheck className="size-5" />
        </div>
        <CardTitle>Masuk ke Control Panel</CardTitle>
        <CardDescription>
          Akun operator JAWARA. Dibuat oleh administrator, bukan pendaftaran mandiri.
        </CardDescription>
      </CardHeader>

      <CardContent>
        <form onSubmit={onSubmit} className="flex flex-col gap-4" noValidate>
          {error ? (
            <Alert variant="destructive" role="alert">
              <AlertDescription>{error}</AlertDescription>
            </Alert>
          ) : null}

          <div className="flex flex-col gap-2">
            <Label htmlFor="email">Email</Label>
            <Input
              id="email"
              name="email"
              type="email"
              autoComplete="username"
              required
              autoFocus
              value={email}
              onChange={(event) => setEmail(event.target.value)}
              placeholder="operator@instansi.go.id"
              disabled={submitting}
            />
          </div>

          <div className="flex flex-col gap-2">
            <Label htmlFor="password">Kata sandi</Label>
            <Input
              id="password"
              name="password"
              type="password"
              autoComplete="current-password"
              required
              minLength={8}
              value={password}
              onChange={(event) => setPassword(event.target.value)}
              disabled={submitting}
            />
          </div>

          <Button type="submit" disabled={submitting || !email || password.length < 8}>
            {submitting ? <Loader2 className="size-4 animate-spin" /> : null}
            {submitting ? "Memeriksa…" : "Masuk"}
          </Button>

          <p className="text-xs text-muted-foreground">
            Sesi berakhir otomatis setelah 8 jam. Percobaan masuk dibatasi 5 kali per 5 menit.
          </p>
        </form>
      </CardContent>
    </Card>
  )
}
