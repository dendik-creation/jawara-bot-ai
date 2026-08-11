"use client"

import * as React from "react"
import Link from "next/link"
import { usePathname, useRouter, useSearchParams } from "next/navigation"

import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Card, CardContent, CardHeader } from "@/components/ui/card"
import { toast } from "@/components/ui/toast"
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
import { api, GatewayError, type IncidentSeverity, type Incidents, type IncidentState } from "@/lib/api"

const PAGE_SIZE_OPTIONS = [10, 25, 50] as const
const DEFAULT_PAGE_SIZE = 25

const SEVERITIES: IncidentSeverity[] = ["LOW", "MEDIUM", "HIGH", "CRITICAL"]
const STATES: IncidentState[] = ["OPEN", "INVESTIGATING", "CONTAINED", "RESOLVED", "FALSE_POSITIVE"]

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

export function severityVariant(severity: IncidentSeverity): "high" | "medium" | "low" {
  if (severity === "CRITICAL" || severity === "HIGH") return "high"
  if (severity === "MEDIUM") return "medium"
  return "low"
}

function stateVariant(state: IncidentState): "low" | "high" | "medium" | "unknown" {
  if (state === "RESOLVED" || state === "FALSE_POSITIVE") return "low"
  if (state === "OPEN") return "high"
  if (state === "INVESTIGATING") return "medium"
  return "unknown"
}

export function IncidentList() {
  return (
    <React.Suspense fallback={<IncidentListSkeleton />}>
      <IncidentListInner />
    </React.Suspense>
  )
}

function IncidentListSkeleton() {
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

function IncidentListInner() {
  const router = useRouter()
  const pathname = usePathname()
  const searchParams = useSearchParams()

  const page = parsePage(searchParams.get("page"))
  const pageSize = parsePageSize(searchParams.get("pageSize"))
  const severity = searchParams.get("severity") ?? ""
  const state = searchParams.get("state") ?? ""
  const offset = (page - 1) * pageSize

  const [data, setData] = React.useState<Incidents | null>(null)
  const [loading, setLoading] = React.useState(true)
  const [error, setError] = React.useState<string | null>(null)
  const [creating, setCreating] = React.useState(false)

  const hasFilters = Boolean(severity || state)

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
        const result = await api.incidents(
          {
            limit: pageSize,
            offset,
            severity: severity ? (severity as IncidentSeverity) : undefined,
            state: state ? (state as IncidentState) : undefined,
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
  }, [offset, pageSize, severity, state])

  const hasMore = data ? offset + data.items.length < data.total : false
  const totalPages = data && data.total > 0 ? Math.ceil(data.total / pageSize) : 1

  return (
    <Card>
      <CardHeader className="flex-row justify-end">
        <Button size="sm" onClick={() => setCreating(true)}>
          Buat Incident
        </Button>
      </CardHeader>
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
              <SelectTrigger size="sm" className="h-8 w-[170px]">
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
          {hasFilters ? (
            <Button variant="ghost" size="sm" onClick={() => updateParams({ severity: null, state: null })}>
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
            {hasFilters ? "Tidak ada incident yang cocok dengan filter ini." : "Belum ada incident."}
          </p>
        ) : (
          <div className="overflow-hidden rounded-lg border border-border">
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead className="whitespace-nowrap">Kode</TableHead>
                  <TableHead>Judul</TableHead>
                  <TableHead>Severity</TableHead>
                  <TableHead>State</TableHead>
                  <TableHead>Ditugaskan</TableHead>
                  <TableHead className="text-right">Pesan</TableHead>
                  <TableHead className="text-right">Pengguna</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {data.items.map((item) => (
                  <TableRow
                    key={item.id}
                    className="cursor-pointer"
                    onClick={() => router.push(`/incidents/${item.id}`)}
                  >
                    <TableCell className="align-top font-mono text-xs text-muted-foreground">
                      <Link href={`/incidents/${item.id}`} className="hover:underline" onClick={(e) => e.stopPropagation()}>
                        {item.code}
                      </Link>
                    </TableCell>
                    <TableCell className="min-w-40 align-top text-sm">{item.title}</TableCell>
                    <TableCell className="align-top">
                      <Badge variant={severityVariant(item.severity)}>{item.severity}</Badge>
                    </TableCell>
                    <TableCell className="align-top">
                      <Badge variant={stateVariant(item.state)}>{item.state}</Badge>
                    </TableCell>
                    <TableCell className="align-top text-xs text-muted-foreground">
                      {item.assigned_operator_name ?? "—"}
                    </TableCell>
                    <TableCell className="align-top text-right text-sm tabular-nums">{item.message_count}</TableCell>
                    <TableCell className="align-top text-right text-sm tabular-nums">
                      {item.affected_user_count}
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

      <CreateIncidentDialog
        open={creating}
        onClose={() => setCreating(false)}
        onCreated={(id) => {
          setCreating(false)
          router.push(`/incidents/${id}`)
        }}
      />
    </Card>
  )
}

function CreateIncidentDialog({
  open,
  onClose,
  onCreated,
}: {
  open: boolean
  onClose: () => void
  onCreated: (id: string) => void
}) {
  return (
    <Dialog open={open} onOpenChange={(next) => !next && onClose()}>
      <DialogContent>
        {open ? <CreateIncidentForm onClose={onClose} onCreated={onCreated} /> : null}
      </DialogContent>
    </Dialog>
  )
}

function CreateIncidentForm({
  onClose,
  onCreated,
}: {
  onClose: () => void
  onCreated: (id: string) => void
}) {
  const [title, setTitle] = React.useState("")
  const [severity, setSeverity] = React.useState<IncidentSeverity | "">("")
  const [messageLogIds, setMessageLogIds] = React.useState("")
  const [submitting, setSubmitting] = React.useState(false)
  const [error, setError] = React.useState<string | null>(null)

  const ids = messageLogIds
    .split(/[\s,]+/)
    .map((value) => value.trim())
    .filter(Boolean)

  async function submit() {
    if (!title.trim() || !severity || ids.length === 0) return
    setSubmitting(true)
    setError(null)
    try {
      const incident = await api.createIncident(title, severity, ids)
      onCreated(incident.id)
      toast.success("Incident dibuat", { description: title.trim() })
    } catch (caught) {
      setError(caught instanceof GatewayError ? caught.message : "gagal membuat incident")
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <>
      <DialogHeader>
        <DialogTitle>Buat Incident</DialogTitle>
        <DialogDescription>
          Kelompokkan satu atau lebih Threat (message log id) menjadi satu unit investigasi.
        </DialogDescription>
      </DialogHeader>

      <div className="flex flex-col gap-3">
        <div className="flex flex-col gap-1.5">
          <Label className="text-xs text-muted-foreground">Judul</Label>
          <Input value={title} onChange={(event) => setTitle(event.target.value)} placeholder="mis. Phishing Campaign" />
        </div>
        <div className="flex flex-col gap-1.5">
          <Label className="text-xs text-muted-foreground">Severity</Label>
          <Select value={severity} onValueChange={(value) => setSeverity(value as IncidentSeverity)}>
            <SelectTrigger className="w-full">
              <SelectValue placeholder="Pilih severity" />
            </SelectTrigger>
            <SelectContent>
              {SEVERITIES.map((value) => (
                <SelectItem key={value} value={value}>
                  {value}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </div>
        <div className="flex flex-col gap-1.5">
          <Label className="text-xs text-muted-foreground">Message log ID (satu per baris atau pisahkan koma)</Label>
          <Textarea
            value={messageLogIds}
            onChange={(event) => setMessageLogIds(event.target.value)}
            placeholder="id-threat-1&#10;id-threat-2"
            rows={4}
            className="font-mono text-xs"
          />
          <p className="text-xs text-muted-foreground">{ids.length} id terdeteksi.</p>
        </div>
        {error ? <p className="text-sm text-destructive">{error}</p> : null}
      </div>

      <DialogFooter>
        <Button variant="outline" onClick={onClose} disabled={submitting}>
          Batal
        </Button>
        <Button onClick={submit} disabled={!title.trim() || !severity || ids.length === 0 || submitting}>
          {submitting ? "Membuat…" : "Buat Incident"}
        </Button>
      </DialogFooter>
    </>
  )
}
