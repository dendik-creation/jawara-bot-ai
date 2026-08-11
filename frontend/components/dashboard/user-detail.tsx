"use client"

import * as React from "react"
import Link from "next/link"

import { Badge, riskVariant } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from "@/components/ui/card"
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog"
import { Label } from "@/components/ui/label"
import { Skeleton } from "@/components/ui/skeleton"
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table"
import { Textarea } from "@/components/ui/textarea"
import { toast } from "@/components/ui/toast"
import { api, GatewayError, type UserDetail as UserDetailData, type UserTier } from "@/lib/api"

function tierVariant(tier: UserTier): "high" | "medium" | "unknown" {
  if (tier === "HIGH") return "high"
  if (tier === "MEDIUM") return "medium"
  return "unknown"
}

export function UserDetail({ userHash }: { userHash: string }) {
  const [data, setData] = React.useState<UserDetailData | null>(null)
  const [loading, setLoading] = React.useState(true)
  const [error, setError] = React.useState<string | null>(null)
  const [actioning, setActioning] = React.useState(false)
  const [refreshKey, setRefreshKey] = React.useState(0)

  React.useEffect(() => {
    let cancelled = false
    const controller = new AbortController()

    async function load() {
      setLoading(true)
      setError(null)
      try {
        const result = await api.user(userHash, controller.signal)
        if (!cancelled) setData(result)
      } catch (caught) {
        if (!cancelled) setError(caught instanceof GatewayError ? caught.message : "gateway tidak dapat dihubungi")
      } finally {
        if (!cancelled) setLoading(false)
      }
    }

    void load()
    return () => {
      cancelled = true
      controller.abort()
    }
  }, [userHash, refreshKey])

  if (loading && !data) {
    return (
      <div className="flex flex-col gap-4">
        <Skeleton className="h-32 w-full" />
        <Skeleton className="h-64 w-full" />
      </div>
    )
  }

  if (error && !data) {
    return <p className="text-sm text-muted-foreground">{error}</p>
  }

  if (!data) {
    return <p className="text-sm text-muted-foreground">Pengguna tidak ditemukan.</p>
  }

  return (
    <div className="flex flex-col gap-4">
      <Card>
        <CardHeader className="flex-row flex-wrap items-start justify-between gap-4">
          <div className="flex flex-col gap-1">
            <span className="break-all font-mono text-xs text-muted-foreground">{data.user_hash}</span>
            <CardDescription>
              {data.chat_type} · terdaftar {new Date(data.subscribed_at).toLocaleDateString("id-ID")}
              {data.last_seen ? ` · terakhir aktif ${new Date(data.last_seen).toLocaleString("id-ID")}` : ""}
            </CardDescription>
          </div>
          <div className="flex items-center gap-2">
            <Badge variant={tierVariant(data.tier)}>{data.tier} · {data.score}</Badge>
            {data.blocked ? <Badge variant="high">Diblokir</Badge> : null}
            {!data.is_active ? <Badge variant="outline">Nonaktif</Badge> : null}
          </div>
        </CardHeader>
        <CardContent className="flex flex-col gap-4">
          {error ? <p className="text-sm text-destructive">{error}</p> : null}

          <dl className="grid grid-cols-2 gap-x-4 gap-y-2 text-sm sm:grid-cols-4">
            <div>
              <dt className="text-xs text-muted-foreground">Threat frequency</dt>
              <dd>{data.threat_count}</dd>
            </div>
            <div>
              <dt className="text-xs text-muted-foreground">Kategori dominan</dt>
              <dd>{data.dominant_category ?? "—"}</dd>
            </div>
            <div>
              <dt className="text-xs text-muted-foreground">Status blokir</dt>
              <dd>{data.blocked ? "Diblokir" : "Tidak diblokir"}</dd>
            </div>
            <div>
              <dt className="text-xs text-muted-foreground">Oleh</dt>
              <dd>{data.blocked_by_name ?? "—"}</dd>
            </div>
          </dl>

          {data.block_reason ? (
            <p className="rounded-lg border border-border bg-muted/40 px-3 py-2 text-sm text-muted-foreground">
              Alasan terakhir: {data.block_reason}
            </p>
          ) : null}

          <div className="border-t border-border pt-4">
            <Button
              variant="outline"
              size="sm"
              className={data.blocked ? "" : "text-destructive hover:text-destructive"}
              onClick={() => setActioning(true)}
            >
              {data.blocked ? "Buka blokir" : "Blokir pengguna"}
            </Button>
          </div>
        </CardContent>
      </Card>

      <Card>
        <CardHeader className="flex-row items-center justify-between gap-4">
          <div>
            <CardTitle>Riwayat Threat</CardTitle>
            <CardDescription>10 threat terbaru dari pengguna ini.</CardDescription>
          </div>
          <Button variant="ghost" size="sm" render={<Link href={`/threats?userHash=${data.user_hash}`} />}>
            Lihat semua di Threats
          </Button>
        </CardHeader>
        <CardContent>
          {data.recent_threats.length === 0 ? (
            <p className="text-sm text-muted-foreground">Belum ada threat dari pengguna ini.</p>
          ) : (
            <div className="overflow-hidden rounded-lg border border-border">
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead>Waktu</TableHead>
                    <TableHead>Risiko</TableHead>
                    <TableHead>Kategori</TableHead>
                    <TableHead>State</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {data.recent_threats.map((threat) => (
                    <TableRow key={threat.message_log_id}>
                      <TableCell className="font-mono text-xs text-muted-foreground tabular-nums">
                        {new Date(threat.at).toLocaleString("id-ID")}
                      </TableCell>
                      <TableCell>
                        <Badge variant={riskVariant(threat.risk)}>{threat.risk}</Badge>
                      </TableCell>
                      <TableCell className="text-sm">{threat.threat_category}</TableCell>
                      <TableCell className="text-xs text-muted-foreground">{threat.state}</TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            </div>
          )}
        </CardContent>
      </Card>

      <UserActionDialog
        open={actioning}
        blocked={data.blocked}
        onClose={() => setActioning(false)}
        onDone={() => {
          setActioning(false)
          setRefreshKey((key) => key + 1)
        }}
        userHash={userHash}
      />
    </div>
  )
}

function UserActionDialog({
  open,
  blocked,
  userHash,
  onClose,
  onDone,
}: {
  open: boolean
  blocked: boolean
  userHash: string
  onClose: () => void
  onDone: () => void
}) {
  return (
    <Dialog open={open} onOpenChange={(next) => !next && onClose()}>
      <DialogContent>
        {open ? (
          <UserActionForm key={userHash} blocked={blocked} userHash={userHash} onClose={onClose} onDone={onDone} />
        ) : null}
      </DialogContent>
    </Dialog>
  )
}

function UserActionForm({
  blocked,
  userHash,
  onClose,
  onDone,
}: {
  blocked: boolean
  userHash: string
  onClose: () => void
  onDone: () => void
}) {
  const [reason, setReason] = React.useState("")
  const [submitting, setSubmitting] = React.useState(false)
  const [error, setError] = React.useState<string | null>(null)

  async function submit() {
    if (!reason.trim()) return
    setSubmitting(true)
    setError(null)
    try {
      await api.actionOnUser(userHash, blocked ? "UNBLOCK" : "BLOCK", reason.trim())
      onDone()
      toast.success(blocked ? "Blokir pengguna dibuka" : "Pengguna diblokir")
    } catch (caught) {
      setError(caught instanceof GatewayError ? caught.message : "gagal menyimpan")
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <>
      <DialogHeader>
        <DialogTitle>{blocked ? "Buka blokir pengguna" : "Blokir pengguna"}</DialogTitle>
        <DialogDescription>
          Keputusan keamanan — wajib disertai alasan dan tercatat di Audit Log.
        </DialogDescription>
      </DialogHeader>

      <div className="flex flex-col gap-3">
        <div className="flex flex-col gap-1.5">
          <Label className="text-xs text-muted-foreground">Alasan</Label>
          <Textarea value={reason} onChange={(event) => setReason(event.target.value)} rows={3} />
        </div>
        {error ? <p className="text-sm text-destructive">{error}</p> : null}
      </div>

      <DialogFooter>
        <Button variant="outline" onClick={onClose} disabled={submitting}>
          Batal
        </Button>
        <Button onClick={submit} disabled={!reason.trim() || submitting}>
          {submitting ? "Menyimpan…" : blocked ? "Buka blokir" : "Blokir"}
        </Button>
      </DialogFooter>
    </>
  )
}
