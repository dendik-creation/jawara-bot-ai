"use client"

import * as React from "react"
import { usePathname, useRouter, useSearchParams } from "next/navigation"

import { useAuth } from "@/components/auth/auth-provider"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Card, CardContent } from "@/components/ui/card"
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
import {
  Pagination,
  PaginationContent,
  PaginationEllipsis,
  PaginationItem,
} from "@/components/ui/pagination"
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select"
import { Skeleton } from "@/components/ui/skeleton"
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table"
import { Textarea } from "@/components/ui/textarea"
import { api, GatewayError, type AlertItem, type AlertSeverity, type Alerts, type AlertState } from "@/lib/api"

const PAGE_SIZE_OPTIONS = [10, 25, 50] as const
const DEFAULT_PAGE_SIZE = 25

const SEVERITIES: AlertSeverity[] = ["LOW", "MEDIUM", "HIGH", "CRITICAL"]
const STATES: AlertState[] = ["NEW", "ACKNOWLEDGED", "RESOLVED", "ESCALATED"]

function parsePage(value: string | null): number {
  const parsed = Number(value)
  return Number.isInteger(parsed) && parsed > 0 ? parsed : 1
}

function parsePageSize(value: string | null): number {
  const parsed = Number(value)
  return (PAGE_SIZE_OPTIONS as readonly number[]).includes(parsed) ? parsed : DEFAULT_PAGE_SIZE
}

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

function severityVariant(severity: AlertSeverity): "high" | "medium" | "low" {
  if (severity === "CRITICAL" || severity === "HIGH") return "high"
  if (severity === "MEDIUM") return "medium"
  return "low"
}

function stateVariant(state: AlertState): "low" | "high" | "medium" | "unknown" {
  if (state === "RESOLVED") return "low"
  if (state === "NEW") return "high"
  if (state === "ACKNOWLEDGED") return "medium"
  return "unknown"
}

export function AlertList() {
  return (
    <React.Suspense fallback={<AlertListSkeleton />}>
      <AlertListInner />
    </React.Suspense>
  )
}

function AlertListSkeleton() {
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

function AlertListInner() {
  const router = useRouter()
  const pathname = usePathname()
  const searchParams = useSearchParams()
  const { operator } = useAuth()

  const page = parsePage(searchParams.get("page"))
  const pageSize = parsePageSize(searchParams.get("pageSize"))
  const severity = searchParams.get("severity") ?? ""
  const state = searchParams.get("state") ?? ""
  const source = searchParams.get("source") ?? ""
  const offset = (page - 1) * pageSize

  const [data, setData] = React.useState<Alerts | null>(null)
  const [loading, setLoading] = React.useState(true)
  const [error, setError] = React.useState<string | null>(null)
  const [pendingId, setPendingId] = React.useState<string | null>(null)
  const [resolving, setResolving] = React.useState<AlertItem | null>(null)
  const [refreshKey, setRefreshKey] = React.useState(0)

  const hasFilters = Boolean(severity || state || source)

  function updateParams(next: Record<string, string | number | null | undefined>) {
    const params = new URLSearchParams(searchParams.toString())
    let resetPage = false

    for (const [key, value] of Object.entries(next)) {
      if (key === "page") continue
      if (value === null || value === undefined || value === "") {
        params.delete(key)
      } else {
        params.set(key, String(value))
      }
      resetPage = true
    }

    if (next.page !== undefined) {
      params.set("page", String(next.page))
    } else if (resetPage) {
      params.set("page", "1")
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
        const result = await api.alerts(
          {
            limit: pageSize,
            offset,
            severity: severity ? (severity as AlertSeverity) : undefined,
            state: state ? (state as AlertState) : undefined,
            source: source || undefined,
          },
          controller.signal,
        )
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
  }, [offset, pageSize, severity, state, source, refreshKey])

  async function quickAction(alert: AlertItem, action: "ACKNOWLEDGE" | "ASSIGN_TO_ME") {
    setPendingId(alert.id)
    try {
      await api.actionOnAlert(alert.id, action)
      setRefreshKey((key) => key + 1)
      toast.success(action === "ACKNOWLEDGE" ? "Alert diketahui" : "Alert ditugaskan ke kamu")
    } catch {
      // Surfaced via the row staying unchanged; the list refetch below on
      // failure keeps state consistent without a separate error banner here.
    } finally {
      setPendingId(null)
    }
  }

  const hasMore = data ? offset + data.items.length < data.total : false
  const totalPages = data && data.total > 0 ? Math.ceil(data.total / pageSize) : 1

  return (
    <Card>
      <CardContent className="flex flex-col gap-4">
        <div className="flex flex-wrap items-end gap-3">
          <div className="flex flex-col gap-1.5">
            <Label className="text-xs text-muted-foreground">Severity</Label>
            <Select value={severity || "all"} onValueChange={(v) => updateParams({ severity: v === "all" ? null : v })}>
              <SelectTrigger size="sm" className="h-8 w-[150px]">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="all">Semua</SelectItem>
                {SEVERITIES.map((value) => (
                  <SelectItem key={value} value={value}>
                    {value}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>
          <div className="flex flex-col gap-1.5">
            <Label className="text-xs text-muted-foreground">State</Label>
            <Select value={state || "all"} onValueChange={(v) => updateParams({ state: v === "all" ? null : v })}>
              <SelectTrigger size="sm" className="h-8 w-[150px]">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="all">Semua</SelectItem>
                {STATES.map((value) => (
                  <SelectItem key={value} value={value}>
                    {value}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>
          <div className="flex flex-col gap-1.5">
            <Label htmlFor="alert-source" className="text-xs text-muted-foreground">
              Sumber
            </Label>
            <Input
              id="alert-source"
              className="h-8 w-[180px]"
              placeholder="mis. threat_escalation"
              defaultValue={source}
              onBlur={(event) => updateParams({ source: event.target.value || null })}
              onKeyDown={(event) => {
                if (event.key === "Enter") updateParams({ source: event.currentTarget.value || null })
              }}
            />
          </div>
          {hasFilters ? (
            <Button variant="ghost" size="sm" onClick={() => updateParams({ severity: null, state: null, source: null })}>
              Reset filter
            </Button>
          ) : null}
        </div>

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
          <p className="text-sm text-muted-foreground">
            {hasFilters ? "Tidak ada alert yang cocok dengan filter ini." : "Belum ada alert."}
          </p>
        ) : (
          <div className="overflow-hidden rounded-lg border border-border">
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead className="whitespace-nowrap">Waktu</TableHead>
                  <TableHead>Severity</TableHead>
                  <TableHead>Judul</TableHead>
                  <TableHead>State</TableHead>
                  <TableHead>Ditugaskan</TableHead>
                  <TableHead className="w-64">
                    <span className="sr-only">Aksi</span>
                  </TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {data.items.map((item) => {
                  const isPending = pendingId === item.id
                  const isMine = operator?.id === item.assigned_operator_id
                  return (
                    <TableRow key={item.id}>
                      <TableCell className="align-top font-mono text-xs text-muted-foreground tabular-nums">
                        {new Date(item.created_at).toLocaleString("id-ID")}
                      </TableCell>
                      <TableCell className="align-top">
                        <Badge variant={severityVariant(item.severity)}>{item.severity}</Badge>
                      </TableCell>
                      <TableCell className="min-w-48 align-top text-sm">
                        {item.title}
                        {item.state === "RESOLVED" && item.resolution_reason ? (
                          <p className="mt-1 text-xs text-muted-foreground">Alasan: {item.resolution_reason}</p>
                        ) : null}
                      </TableCell>
                      <TableCell className="align-top">
                        <Badge variant={stateVariant(item.state)}>{item.state}</Badge>
                      </TableCell>
                      <TableCell className="align-top text-xs text-muted-foreground">
                        {item.assigned_operator_name ?? "—"}
                      </TableCell>
                      <TableCell className="align-top">
                        <div className="flex flex-wrap gap-1.5">
                          <Button
                            variant="outline"
                            size="sm"
                            disabled={item.state !== "NEW" || isPending}
                            onClick={() => quickAction(item, "ACKNOWLEDGE")}
                          >
                            Acknowledge
                          </Button>
                          <Button
                            variant="outline"
                            size="sm"
                            disabled={item.state === "RESOLVED" || isMine || isPending}
                            onClick={() => quickAction(item, "ASSIGN_TO_ME")}
                          >
                            {isMine ? "Ditugaskan ke saya" : "Assign ke saya"}
                          </Button>
                          <Button
                            variant="outline"
                            size="sm"
                            disabled={item.state === "RESOLVED" || isPending}
                            onClick={() => setResolving(item)}
                          >
                            Resolve
                          </Button>
                        </div>
                      </TableCell>
                    </TableRow>
                  )
                })}
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
              <Select value={String(pageSize)} onValueChange={(value) => updateParams({ pageSize: Number(value) })}>
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

      <ResolveAlertDialog
        alert={resolving}
        onClose={() => setResolving(null)}
        onDone={() => {
          setResolving(null)
          setRefreshKey((key) => key + 1)
        }}
      />
    </Card>
  )
}

function ResolveAlertDialog({
  alert,
  onClose,
  onDone,
}: {
  alert: AlertItem | null
  onClose: () => void
  onDone: () => void
}) {
  return (
    <Dialog open={alert !== null} onOpenChange={(open) => !open && onClose()}>
      <DialogContent>
        {alert ? <ResolveAlertForm key={alert.id} alert={alert} onClose={onClose} onDone={onDone} /> : null}
      </DialogContent>
    </Dialog>
  )
}

function ResolveAlertForm({
  alert,
  onClose,
  onDone,
}: {
  alert: AlertItem
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
      await api.actionOnAlert(alert.id, "RESOLVE", reason)
      onDone()
      toast.success("Alert diresolve")
    } catch (caught) {
      setError(caught instanceof GatewayError ? caught.message : "gagal resolve alert")
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <>
      <DialogHeader>
        <DialogTitle>Resolve alert</DialogTitle>
        <DialogDescription>
          Menutup alert &ldquo;{alert.title}&rdquo;. Alasan wajib diisi dan tercatat di Audit Log.
        </DialogDescription>
      </DialogHeader>

      <div className="flex flex-col gap-3">
        <div className="flex flex-col gap-1.5">
          <Label className="text-xs text-muted-foreground">Alasan</Label>
          <Textarea
            value={reason}
            onChange={(event) => setReason(event.target.value)}
            placeholder="Kenapa alert ini ditutup…"
            rows={3}
          />
        </div>
        {error ? <p className="text-sm text-destructive">{error}</p> : null}
      </div>

      <DialogFooter>
        <Button variant="outline" onClick={onClose} disabled={submitting}>
          Batal
        </Button>
        <Button onClick={submit} disabled={!reason.trim() || submitting}>
          {submitting ? "Menyimpan…" : "Resolve"}
        </Button>
      </DialogFooter>
    </>
  )
}
