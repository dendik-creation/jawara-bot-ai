"use client"

import * as React from "react"
import { Loader2 } from "lucide-react"

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
 * Self-service password change, opened from the operator menu.
 *
 * Controlled by `open`/`onOpenChange` rather than a `DialogTrigger` because the
 * trigger is a `DropdownMenuItem` — composing one Base UI popup's trigger prop
 * with another unmounts the menu before the dialog would mount.
 */
export function ChangePasswordDialog({
  open,
  onOpenChange,
}: {
  open: boolean
  onOpenChange: (open: boolean) => void
}) {
  const [currentPassword, setCurrentPassword] = React.useState("")
  const [newPassword, setNewPassword] = React.useState("")
  const [confirmPassword, setConfirmPassword] = React.useState("")
  const [error, setError] = React.useState<string | null>(null)
  const [submitting, setSubmitting] = React.useState(false)

  function reset() {
    setCurrentPassword("")
    setNewPassword("")
    setConfirmPassword("")
    setError(null)
    setSubmitting(false)
  }

  function handleOpenChange(next: boolean) {
    if (!next) reset()
    onOpenChange(next)
  }

  async function onSubmit(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault()
    if (newPassword !== confirmPassword) {
      setError("Konfirmasi kata sandi baru tidak cocok")
      return
    }
    setSubmitting(true)
    setError(null)
    try {
      await api.changePassword(currentPassword, newPassword)
      handleOpenChange(false)
      toast.success("Kata sandi diganti", { description: "Gunakan kata sandi baru untuk sesi masuk berikutnya." })
    } catch (caught) {
      setError(
        caught instanceof GatewayError
          ? caught.message
          : "Tidak dapat menghubungi gateway. Coba lagi.",
      )
      setSubmitting(false)
    }
  }

  return (
    <Dialog open={open} onOpenChange={handleOpenChange}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>Ganti kata sandi</DialogTitle>
          <DialogDescription>
            Sesi lain milik akun ini tidak otomatis keluar setelah ini diganti.
          </DialogDescription>
        </DialogHeader>

        <form onSubmit={onSubmit} className="flex flex-col gap-4" noValidate>
          {error ? (
            <Alert variant="destructive" role="alert">
              <AlertDescription>{error}</AlertDescription>
            </Alert>
          ) : null}

          <div className="flex flex-col gap-2">
            <Label htmlFor="current-password">Kata sandi saat ini</Label>
            <Input
              id="current-password"
              type="password"
              autoComplete="current-password"
              required
              minLength={8}
              autoFocus
              value={currentPassword}
              onChange={(event) => setCurrentPassword(event.target.value)}
              disabled={submitting}
            />
          </div>

          <div className="flex flex-col gap-2">
            <Label htmlFor="new-password">Kata sandi baru</Label>
            <Input
              id="new-password"
              type="password"
              autoComplete="new-password"
              required
              minLength={8}
              value={newPassword}
              onChange={(event) => setNewPassword(event.target.value)}
              disabled={submitting}
            />
          </div>

          <div className="flex flex-col gap-2">
            <Label htmlFor="confirm-password">Ulangi kata sandi baru</Label>
            <Input
              id="confirm-password"
              type="password"
              autoComplete="new-password"
              required
              minLength={8}
              value={confirmPassword}
              onChange={(event) => setConfirmPassword(event.target.value)}
              disabled={submitting}
            />
          </div>

          <DialogFooter>
            <Button
              type="submit"
              disabled={
                submitting ||
                currentPassword.length < 8 ||
                newPassword.length < 8 ||
                confirmPassword.length < 8
              }
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
