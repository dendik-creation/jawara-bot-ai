"use client"

import * as React from "react"
import { Loader2 } from "lucide-react"

import { useAuth } from "@/components/auth/auth-provider"
import { Alert, AlertDescription } from "@/components/ui/alert"
import { Button } from "@/components/ui/button"
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { toast } from "@/components/ui/toast"
import { api, GatewayError } from "@/lib/api"

/**
 * Self-service display-name edit, opened from the operator menu.
 *
 * Name only — no avatar. Avatar upload would need a backend storage decision
 * that doesn't exist yet, and a disabled control that can never be used isn't
 * worth the space.
 *
 * Controlled by `open`/`onOpenChange` for the same reason as
 * `ChangePasswordDialog`: the trigger is a `DropdownMenuItem`.
 */
export function EditProfileDialog({
  open,
  onOpenChange,
}: {
  open: boolean
  onOpenChange: (open: boolean) => void
}) {
  const { operator, updateOperator } = useAuth()
  const [fullName, setFullName] = React.useState(operator?.full_name ?? "")
  const [error, setError] = React.useState<string | null>(null)
  const [submitting, setSubmitting] = React.useState(false)

  function reset() {
    setFullName(operator?.full_name ?? "")
    setError(null)
    setSubmitting(false)
  }

  function handleOpenChange(next: boolean) {
    if (next) reset()
    onOpenChange(next)
  }

  async function onSubmit(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault()
    setSubmitting(true)
    setError(null)
    try {
      const updated = await api.updateProfile(fullName.trim())
      updateOperator(updated)
      handleOpenChange(false)
      toast.success("Profil diperbarui", { description: `Nama tampilan diganti ke "${updated.full_name}".` })
    } catch (caught) {
      setError(
        caught instanceof GatewayError
          ? caught.message
          : "Tidak dapat menghubungi gateway. Coba lagi.",
      )
      setSubmitting(false)
    }
  }

  if (!operator) return null

  return (
    <Dialog open={open} onOpenChange={handleOpenChange}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>Edit profil</DialogTitle>
          <DialogDescription>Perbarui nama tampilan akun operator ini.</DialogDescription>
        </DialogHeader>

        <form onSubmit={onSubmit} className="flex flex-col gap-4" noValidate>
          {error ? (
            <Alert variant="destructive" role="alert">
              <AlertDescription>{error}</AlertDescription>
            </Alert>
          ) : null}

          <div className="flex flex-col gap-2">
            <Label htmlFor="full-name">Nama lengkap</Label>
            <Input
              id="full-name"
              autoComplete="name"
              required
              minLength={1}
              maxLength={200}
              autoFocus
              value={fullName}
              onChange={(event) => setFullName(event.target.value)}
              disabled={submitting}
            />
          </div>

          <div className="flex flex-col gap-2">
            <Label htmlFor="email">Email</Label>
            <Input id="email" value={operator.email} disabled readOnly />
          </div>

          <DialogFooter>
            <Button
              type="submit"
              disabled={submitting || fullName.trim().length === 0}
            >
              {submitting ? <Loader2 className="size-4 animate-spin" /> : null}
              {submitting ? "Menyimpan…" : "Simpan"}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  )
}
