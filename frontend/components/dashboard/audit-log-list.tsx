"use client"

import * as React from "react"
import { usePathname, useRouter, useSearchParams } from "next/navigation"

import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from "@/components/ui/card"
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
import { api, GatewayError, type AuditLog, type AuditResult } from "@/lib/api"

const PAGE_SIZE_OPTIONS = [10, 25, 50] as const
const DEFAULT_PAGE_SIZE = 25

// Only actions that actually exist today write rows with this value — this
// list grows as later stages add their own `record_audit` calls, never ahead
// of them.
const KNOWN_ACTIONS = ["operator.login", "operator.logout", "operator.change_password"] as const

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

function resultVariant(result: AuditResult): "low" | "high" | "medium" {
  // Reusing the risk-level badge tokens for their color meaning (green/red/
  // amber), not their original risk semantics.
  if (result === "SUCCESS") return "low"
  if (result === "DENIED") return "medium"
  return "high"
}

function formatMetadata(metadata: Record<string, unknown>): string {
  const entries = Object.entries(metadata)
  if (entries.length === 0) return "—"
  return entries.map(([key, value]) => `${key}: ${value}`).join(" · ")
}

export function AuditLogList() {
  return (
    <React.Suspense fallback={<AuditLogSkeleton />}>
      <AuditLogListInner />
    </React.Suspense>
  )
}

function AuditLogSkeleton() {
  return (
    <Card>
      <CardHeader>
        <CardTitle>Audit Log</CardTitle>
        <CardDescription>Jejak aksi operator: siapa melakukan apa, kapan, dan hasilnya.</CardDescription>
      </CardHeader>
      <CardContent className="flex flex-col gap-2">
        {Array.from({ length: 6 }).map((_, index) => (
          <Skeleton key={index} className="h-10 w-full" />
        ))}
      </CardContent>
    </Card>
  )
}

function AuditLogListInner() {
  const router = useRouter()
  const pathname = usePathname()
  const searchParams = useSearchParams()

  const page = parsePage(searchParams.get("page"))
  const pageSize = parsePageSize(searchParams.get("pageSize"))
  const action = searchParams.get("action") ?? ""
  const dateFrom = searchParams.get("dateFrom") ?? ""
  const dateTo = searchParams.get("dateTo") ?? ""
  const offset = (page - 1) * pageSize

  const [data, setData] = React.useState<AuditLog | null>(null)
  const [loading, setLoading] = React.useState(true)
  const [error, setError] = React.useState<string | null>(null)

  function updateParams(next: {
    page?: number
    pageSize?: number
    action?: string | null
    dateFrom?: string | null
    dateTo?: string | null
  }) {
    const params = new URLSearchParams(searchParams.toString())

    if (next.pageSize !== undefined) {
      params.set("pageSize", String(next.pageSize))
      params.set("page", "1")
    }
    if (next.action !== undefined) {
      if (next.action) params.set("action", next.action)
      else params.delete("action")
      params.set("page", "1")
    }
    if (next.dateFrom !== undefined) {
      if (next.dateFrom) params.set("dateFrom", next.dateFrom)
      else params.delete("dateFrom")
      params.set("page", "1")
    }
    if (next.dateTo !== undefined) {
      if (next.dateTo) params.set("dateTo", next.dateTo)
      else params.delete("dateTo")
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
        const result = await api.auditLog(
          {
            limit: pageSize,
            offset,
            action: action || undefined,
            dateFrom: dateFrom ? new Date(dateFrom).toISOString() : undefined,
            dateTo: dateTo ? new Date(dateTo).toISOString() : undefined,
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
  }, [offset, pageSize, action, dateFrom, dateTo])

  const hasMore = data ? offset + data.items.length < data.total : false
  const totalPages = data && data.total > 0 ? Math.ceil(data.total / pageSize) : 1

  return (
    <Card>
      <CardHeader>
        <CardTitle>Audit Log</CardTitle>
        <CardDescription>Jejak aksi operator: siapa melakukan apa, kapan, dan hasilnya.</CardDescription>
      </CardHeader>
      <CardContent className="flex flex-col gap-4">
        <div className="flex flex-wrap items-end gap-3">
          <div className="flex flex-col gap-1.5">
            <Label htmlFor="audit-action" className="text-xs text-muted-foreground">
              Aksi
            </Label>
            <Select value={action || "all"} onValueChange={(value) => updateParams({ action: value === "all" ? null : value })}>
              <SelectTrigger id="audit-action" size="sm" className="h-8 w-[220px]">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="all">Semua aksi</SelectItem>
                {KNOWN_ACTIONS.map((value) => (
                  <SelectItem key={value} value={value}>
                    {value}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>
          <div className="flex flex-col gap-1.5">
            <Label htmlFor="audit-from" className="text-xs text-muted-foreground">
              Dari tanggal
            </Label>
            <Input
              id="audit-from"
              type="date"
              className="h-8 w-[160px]"
              value={dateFrom}
              onChange={(event) => updateParams({ dateFrom: event.target.value || null })}
            />
          </div>
          <div className="flex flex-col gap-1.5">
            <Label htmlFor="audit-to" className="text-xs text-muted-foreground">
              Sampai tanggal
            </Label>
            <Input
              id="audit-to"
              type="date"
              className="h-8 w-[160px]"
              value={dateTo}
              onChange={(event) => updateParams({ dateTo: event.target.value || null })}
            />
          </div>
          {action || dateFrom || dateTo ? (
            <Button
              variant="ghost"
              size="sm"
              onClick={() => updateParams({ action: null, dateFrom: null, dateTo: null })}
            >
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
            {action || dateFrom || dateTo
              ? "Tidak ada entri yang cocok dengan filter ini."
              : "Belum ada aksi operator yang tercatat."}
          </p>
        ) : (
          <div className="overflow-hidden rounded-lg border border-border">
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead className="whitespace-nowrap">Waktu</TableHead>
                  <TableHead>Aktor</TableHead>
                  <TableHead>Aksi</TableHead>
                  <TableHead>Target</TableHead>
                  <TableHead>Hasil</TableHead>
                  <TableHead>Detail</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {data.items.map((item) => (
                  <TableRow key={item.id}>
                    <TableCell className="align-top font-mono text-xs text-muted-foreground tabular-nums">
                      {new Date(item.at).toLocaleString("id-ID")}
                    </TableCell>
                    <TableCell className="align-top text-sm">
                      {item.actor_name ?? <span className="text-muted-foreground">—</span>}
                    </TableCell>
                    <TableCell className="align-top font-mono text-xs">{item.action}</TableCell>
                    <TableCell className="align-top text-xs text-muted-foreground">
                      {item.target_type}
                      {item.target_id ? ` · ${item.target_id.slice(0, 8)}…` : ""}
                    </TableCell>
                    <TableCell className="align-top">
                      <Badge variant={resultVariant(item.result)}>{item.result}</Badge>
                    </TableCell>
                    <TableCell className="min-w-40 align-top text-xs text-muted-foreground whitespace-normal">
                      {formatMetadata(item.metadata)}
                      {item.ip_address ? ` · ${item.ip_address}` : ""}
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
    </Card>
  )
}
