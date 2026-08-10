"use client"

import * as React from "react"
import { Trash2 } from "lucide-react"

import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
} from "@/components/ui/alert-dialog"
import { Badge, riskVariant } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card"
import { api, GatewayError, type MessageLogItem, type MessageLogs } from "@/lib/api"

const PAGE_SIZE = 20

/**
 * Message Inspection ([[04_Message_Inspection]]) — the only screen that shows
 * `extracted_text`. Every other Control Panel view is metadata-only on
 * purpose; this one exists specifically so an operator can read it, and
 * delete it, per the retention decision in [[Open_Decisions_Carried_Forward]]
 * §2.3: kept indefinitely, readable by any signed-in operator (no RBAC tiers
 * exist), removed only by explicit per-row action — no scheduled purge.
 */
export function MessageInspection() {
  const [data, setData] = React.useState<MessageLogs | null>(null)
  const [offset, setOffset] = React.useState(0)
  const [loading, setLoading] = React.useState(true)
  const [error, setError] = React.useState<string | null>(null)
  const [pendingDelete, setPendingDelete] = React.useState<MessageLogItem | null>(null)
  const [deleting, setDeleting] = React.useState(false)

  React.useEffect(() => {
    let cancelled = false
    const controller = new AbortController()

    async function load() {
      setLoading(true)
      setError(null)
      try {
        const result = await api.messages(PAGE_SIZE, offset, controller.signal)
        if (cancelled) return
        setData(result)
      } catch (caught) {
        if (cancelled) return
        setError(caught instanceof GatewayError ? caught.message : "gateway tidak dapat dihubungi")
      } finally {
        if (!cancelled) setLoading(false)
      }
    }

    void load()

    return () => {
      cancelled = true
      controller.abort()
    }
  }, [offset])

  async function confirmDelete() {
    if (!pendingDelete) return
    setDeleting(true)
    try {
      await api.deleteMessage(pendingDelete.id)
      setData((current) =>
        current
          ? {
              ...current,
              total: current.total - 1,
              items: current.items.filter((item) => item.id !== pendingDelete.id),
            }
          : current,
      )
      setPendingDelete(null)
    } catch (caught) {
      setError(caught instanceof GatewayError ? caught.message : "gagal menghapus")
    } finally {
      setDeleting(false)
    }
  }

  const hasMore = data ? offset + data.items.length < data.total : false

  return (
    <Card>
      <CardHeader>
        <CardTitle>Message Inspection</CardTitle>
        <CardDescription>
          Isi pesan asli pengguna. Disimpan tanpa batas waktu — hapus manual per baris kalau perlu.
        </CardDescription>
      </CardHeader>
      <CardContent className="flex flex-col gap-4">
        {error ? (
          <p className="text-sm text-muted-foreground">{error}</p>
        ) : loading && !data ? (
          <p className="text-sm text-muted-foreground">Memuat…</p>
        ) : !data?.available ? (
          <p className="text-sm text-muted-foreground">Belum tersedia ({data?.reason ?? "tidak diketahui"}).</p>
        ) : data.items.length === 0 ? (
          <p className="text-sm text-muted-foreground">Belum ada pesan tercatat.</p>
        ) : (
          <ul className="flex flex-col divide-y divide-border">
            {data.items.map((item) => (
              <li key={item.id} className="flex flex-col gap-2 py-3">
                <div className="flex flex-wrap items-center gap-2">
                  <span className="font-mono text-xs text-muted-foreground tabular-nums">
                    {new Date(item.at).toLocaleString("id-ID")}
                  </span>
                  <Badge variant={riskVariant(item.risk)}>{item.risk}</Badge>
                  <Badge variant="outline">{item.intent ?? "UNCLASSIFIED"}</Badge>
                  <Badge variant="outline">{item.threat_category}</Badge>
                  <span className="text-xs text-muted-foreground">
                    {item.chat_type} · {item.input_type}
                    {item.latency_ms !== null ? ` · ${item.latency_ms} ms` : ""}
                  </span>
                  <Button
                    variant="ghost"
                    size="icon-sm"
                    className="ml-auto text-muted-foreground hover:text-destructive"
                    aria-label="Hapus pesan"
                    onClick={() => setPendingDelete(item)}
                  >
                    <Trash2 className="size-4" />
                  </Button>
                </div>
                <p className="text-sm whitespace-pre-wrap">
                  {item.extracted_text ?? <span className="text-muted-foreground">(tidak ada teks)</span>}
                </p>
              </li>
            ))}
          </ul>
        )}

        {data?.available && data.items.length > 0 ? (
          <div className="flex items-center justify-between text-xs text-muted-foreground">
            <span>
              {offset + 1}–{offset + data.items.length} dari {data.total}
            </span>
            <div className="flex gap-2">
              <Button
                variant="outline"
                size="sm"
                disabled={offset === 0 || loading}
                onClick={() => setOffset(Math.max(0, offset - PAGE_SIZE))}
              >
                Sebelumnya
              </Button>
              <Button
                variant="outline"
                size="sm"
                disabled={!hasMore || loading}
                onClick={() => setOffset(offset + PAGE_SIZE)}
              >
                Berikutnya
              </Button>
            </div>
          </div>
        ) : null}
      </CardContent>

      <AlertDialog open={pendingDelete !== null} onOpenChange={(open) => !open && setPendingDelete(null)}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>Hapus pesan ini?</AlertDialogTitle>
            <AlertDialogDescription>
              Tidak bisa dibatalkan — baris ini akan hilang permanen dari message_logs.
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel disabled={deleting}>Batal</AlertDialogCancel>
            <AlertDialogAction
              disabled={deleting}
              className="bg-destructive text-destructive-foreground hover:bg-destructive/90"
              onClick={confirmDelete}
            >
              {deleting ? "Menghapus…" : "Hapus"}
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </Card>
  )
}
