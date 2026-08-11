"use client"

import * as React from "react"
import { usePathname, useRouter, useSearchParams } from "next/navigation"
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
import { Card, CardContent } from "@/components/ui/card"
import { toast } from "@/components/ui/toast"
import {
  Pagination,
  PaginationContent,
  PaginationEllipsis,
  PaginationItem,
} from "@/components/ui/pagination"
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select"
import { Skeleton } from "@/components/ui/skeleton"
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table"
import { api, GatewayError, type MessageLogItem, type MessageLogs } from "@/lib/api"

const PAGE_SIZE_OPTIONS = [10, 25, 50] as const
const DEFAULT_PAGE_SIZE = 25

function parsePage(value: string | null): number {
  const parsed = Number(value)
  return Number.isInteger(parsed) && parsed > 0 ? parsed : 1
}

function parsePageSize(value: string | null): number {
  const parsed = Number(value)
  return (PAGE_SIZE_OPTIONS as readonly number[]).includes(parsed) ? parsed : DEFAULT_PAGE_SIZE
}

/** Windows the page-number strip around the current page instead of listing every page. */
function pageWindow(current: number, total: number): (number | "ellipsis")[] {
  if (total <= 7) return Array.from({ length: total }, (_, i) => i + 1)

  const keep = new Set([1, total, current - 1, current, current + 1])
  const sorted = [...keep].filter((page) => page >= 1 && page <= total).sort((a, b) => a - b)

  const result: (number | "ellipsis")[] = []
  let previous = 0
  for (const page of sorted) {
    if (previous && page - previous > 1) result.push("ellipsis")
    result.push(page)
    previous = page
  }
  return result
}

/**
 * Message Inspection ([[04_Message_Inspection]]) — the only screen that shows
 * `extracted_text`. Every other Control Panel view is metadata-only on
 * purpose; this one exists specifically so an operator can read it, and
 * delete it, per the retention decision in [[Open_Decisions_Carried_Forward]]
 * §2.3: kept indefinitely, readable by any signed-in operator (no RBAC tiers
 * exist), removed only by explicit per-row action — no scheduled purge.
 */
export function MessageInspection() {
  return (
    <React.Suspense fallback={<MessageInspectionSkeleton />}>
      <MessageInspectionInner />
    </React.Suspense>
  )
}

function MessageInspectionSkeleton() {
  return (
    <Card>
      <CardContent className="flex flex-col gap-2">
        {Array.from({ length: 6 }).map((_, index) => (
          <Skeleton key={index} className="h-10 w-full" />
        ))}
      </CardContent>
    </Card>
  )
}

function MessageInspectionInner() {
  const router = useRouter()
  const pathname = usePathname()
  const searchParams = useSearchParams()

  const page = parsePage(searchParams.get("page"))
  const pageSize = parsePageSize(searchParams.get("pageSize"))
  const offset = (page - 1) * pageSize

  const [data, setData] = React.useState<MessageLogs | null>(null)
  const [loading, setLoading] = React.useState(true)
  const [error, setError] = React.useState<string | null>(null)
  const [pendingDelete, setPendingDelete] = React.useState<MessageLogItem | null>(null)
  const [deleting, setDeleting] = React.useState(false)

  function updateParams(next: { page?: number; pageSize?: number }) {
    const params = new URLSearchParams(searchParams.toString())
    if (next.pageSize !== undefined) {
      params.set("pageSize", String(next.pageSize))
      params.set("page", "1")
    }
    if (next.page !== undefined) {
      params.set("page", String(next.page))
    }
    router.replace(`${pathname}?${params.toString()}`, { scroll: false })
  }

  React.useEffect(() => {
    let cancelled = false
    const controller = new AbortController()

    async function load() {
      setLoading(true)
      setError(null)
      try {
        const result = await api.messages(pageSize, offset, controller.signal)
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
  }, [offset, pageSize])

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
      toast.success("Pesan dihapus")
    } catch (caught) {
      setError(caught instanceof GatewayError ? caught.message : "gagal menghapus")
    } finally {
      setDeleting(false)
    }
  }

  const hasMore = data ? offset + data.items.length < data.total : false
  const totalPages = data && data.total > 0 ? Math.ceil(data.total / pageSize) : 1

  return (
    <Card>
      <CardContent className="flex flex-col gap-4">
        {error ? (
          <p className="text-sm text-muted-foreground">{error}</p>
        ) : loading && !data ? (
          <div className="flex flex-col gap-2">
            {Array.from({ length: 6 }).map((_, index) => (
              <Skeleton key={index} className="h-10 w-full" />
            ))}
          </div>
        ) : !data?.available ? (
          <p className="text-sm text-muted-foreground">Belum tersedia ({data?.reason ?? "tidak diketahui"}).</p>
        ) : data.items.length === 0 ? (
          <p className="text-sm text-muted-foreground">Belum ada pesan tercatat.</p>
        ) : (
          <div className="overflow-hidden rounded-lg border border-border">
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead className="whitespace-nowrap">Waktu</TableHead>
                  <TableHead>Risiko</TableHead>
                  <TableHead>Pesan</TableHead>
                  <TableHead className="whitespace-nowrap">Metadata</TableHead>
                  <TableHead className="w-10">
                    <span className="sr-only">Aksi</span>
                  </TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {data.items.map((item) => (
                  <TableRow key={item.id}>
                    <TableCell className="align-top font-mono text-xs text-muted-foreground tabular-nums">
                      {new Date(item.at).toLocaleString("id-ID")}
                    </TableCell>
                    <TableCell className="align-top">
                      <Badge variant={riskVariant(item.risk)}>{item.risk}</Badge>
                    </TableCell>
                    <TableCell className="max-w-md min-w-64 align-top text-sm whitespace-normal">
                      {item.extracted_text ?? <span className="text-muted-foreground">(tidak ada teks)</span>}
                    </TableCell>
                    <TableCell className="min-w-40 align-top text-xs text-muted-foreground whitespace-normal">
                      {item.intent ?? "UNCLASSIFIED"} · {item.threat_category} · {item.chat_type} ·{" "}
                      {item.input_type}
                      {item.latency_ms !== null ? ` · ${item.latency_ms} ms` : ""}
                    </TableCell>
                    <TableCell className="align-top">
                      <Button
                        variant="ghost"
                        size="icon"
                        className="text-muted-foreground hover:text-destructive"
                        aria-label="Hapus pesan"
                        onClick={() => setPendingDelete(item)}
                      >
                        <Trash2 className="size-4" />
                      </Button>
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </div>
        )}

        {data?.available && data.items.length > 0 ? (
          <div className="flex flex-col gap-3 border-t border-border pt-4 sm:flex-row sm:items-center sm:justify-between">
            <div className="flex items-center gap-2 text-xs text-muted-foreground">
              <span>
                {offset + 1}–{offset + data.items.length} dari {data.total}
              </span>
              <Select
                value={String(pageSize)}
                onValueChange={(value) => updateParams({ pageSize: Number(value) })}
              >
                <SelectTrigger size="sm" className="h-7 w-[112px]" aria-label="Baris per halaman">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  {PAGE_SIZE_OPTIONS.map((size) => (
                    <SelectItem key={size} value={String(size)}>
                      {size} / halaman
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>

            <Pagination className="mx-0 w-fit">
              <PaginationContent>
                <PaginationItem>
                  <Button
                    variant="outline"
                    size="sm"
                    disabled={page === 1 || loading}
                    onClick={() => updateParams({ page: page - 1 })}
                  >
                    Sebelumnya
                  </Button>
                </PaginationItem>
                {pageWindow(page, totalPages).map((entry, index) =>
                  entry === "ellipsis" ? (
                    <PaginationItem key={`ellipsis-${index}`}>
                      <PaginationEllipsis />
                    </PaginationItem>
                  ) : (
                    <PaginationItem key={entry}>
                      <Button
                        variant={entry === page ? "outline" : "ghost"}
                        size="icon-sm"
                        aria-current={entry === page ? "page" : undefined}
                        disabled={loading}
                        onClick={() => updateParams({ page: entry })}
                      >
                        {entry}
                      </Button>
                    </PaginationItem>
                  ),
                )}
                <PaginationItem>
                  <Button
                    variant="outline"
                    size="sm"
                    disabled={!hasMore || loading}
                    onClick={() => updateParams({ page: page + 1 })}
                  >
                    Berikutnya
                  </Button>
                </PaginationItem>
              </PaginationContent>
            </Pagination>
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
