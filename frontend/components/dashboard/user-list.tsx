"use client"

import * as React from "react"
import { useRouter, useSearchParams, usePathname } from "next/navigation"

import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from "@/components/ui/card"
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
import { api, GatewayError, type UserChatType, type UserTier, type Users } from "@/lib/api"

const PAGE_SIZE_OPTIONS = [10, 25, 50] as const
const DEFAULT_PAGE_SIZE = 25

const TIERS: UserTier[] = ["HIGH", "MEDIUM", "NONE"]
const CHAT_TYPES: UserChatType[] = ["PERSONAL", "GROUP"]

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

function tierVariant(tier: UserTier): "high" | "medium" | "unknown" {
  if (tier === "HIGH") return "high"
  if (tier === "MEDIUM") return "medium"
  return "unknown"
}

function truncateHash(hash: string): string {
  return `${hash.slice(0, 8)}…${hash.slice(-6)}`
}

export function UserList() {
  return (
    <React.Suspense fallback={<UserListSkeleton />}>
      <UserListInner />
    </React.Suspense>
  )
}

function UserListSkeleton() {
  return (
    <Card>
      <CardHeader>
        <CardTitle>Users</CardTitle>
        <CardDescription>Populasi pengguna WhatsApp yang dianalisis platform.</CardDescription>
      </CardHeader>
      <CardContent className="flex flex-col gap-2">
        {Array.from({ length: 6 }).map((_, index) => (
          <Skeleton key={index} className="h-10 w-full" />
        ))}
      </CardContent>
    </Card>
  )
}

function UserListInner() {
  const router = useRouter()
  const pathname = usePathname()
  const searchParams = useSearchParams()

  const page = parsePage(searchParams.get("page"))
  const pageSize = parsePageSize(searchParams.get("pageSize"))
  const tier = searchParams.get("tier") ?? ""
  const chatType = searchParams.get("chatType") ?? ""
  const isActive = searchParams.get("isActive") ?? ""
  const blocked = searchParams.get("blocked") ?? ""
  const offset = (page - 1) * pageSize

  const [data, setData] = React.useState<Users | null>(null)
  const [loading, setLoading] = React.useState(true)
  const [error, setError] = React.useState<string | null>(null)

  const hasFilters = Boolean(tier || chatType || isActive || blocked)

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
        const result = await api.users(
          {
            limit: pageSize,
            offset,
            tier: tier ? (tier as UserTier) : undefined,
            chatType: chatType ? (chatType as UserChatType) : undefined,
            isActive: isActive ? isActive === "true" : undefined,
            blocked: blocked ? blocked === "true" : undefined,
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
  }, [offset, pageSize, tier, chatType, isActive, blocked])

  const hasMore = data ? offset + data.items.length < data.total : false
  const totalPages = data && data.total > 0 ? Math.ceil(data.total / pageSize) : 1

  return (
    <Card>
      <CardHeader>
        <CardTitle>Users</CardTitle>
        <CardDescription>Populasi pengguna WhatsApp yang dianalisis platform.</CardDescription>
      </CardHeader>
      <CardContent className="flex flex-col gap-4">
        <div className="flex flex-wrap items-end gap-3">
          <div className="flex flex-col gap-1.5">
            <Label className="text-xs text-muted-foreground">Risk tier</Label>
            <Select value={tier || "all"} onValueChange={(v) => updateParams({ tier: v === "all" ? null : v })}>
              <SelectTrigger size="sm" className="h-8 w-[140px]">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="all">Semua</SelectItem>
                {TIERS.map((value) => (
                  <SelectItem key={value} value={value}>
                    {value}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>
          <div className="flex flex-col gap-1.5">
            <Label className="text-xs text-muted-foreground">Chat type</Label>
            <Select
              value={chatType || "all"}
              onValueChange={(v) => updateParams({ chatType: v === "all" ? null : v })}
            >
              <SelectTrigger size="sm" className="h-8 w-[140px]">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="all">Semua</SelectItem>
                {CHAT_TYPES.map((value) => (
                  <SelectItem key={value} value={value}>
                    {value}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>
          <div className="flex flex-col gap-1.5">
            <Label className="text-xs text-muted-foreground">Status langganan</Label>
            <Select
              value={isActive || "all"}
              onValueChange={(v) => updateParams({ isActive: v === "all" ? null : v })}
            >
              <SelectTrigger size="sm" className="h-8 w-[140px]">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="all">Semua</SelectItem>
                <SelectItem value="true">Aktif</SelectItem>
                <SelectItem value="false">Nonaktif</SelectItem>
              </SelectContent>
            </Select>
          </div>
          <div className="flex flex-col gap-1.5">
            <Label className="text-xs text-muted-foreground">Blokir</Label>
            <Select value={blocked || "all"} onValueChange={(v) => updateParams({ blocked: v === "all" ? null : v })}>
              <SelectTrigger size="sm" className="h-8 w-[140px]">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="all">Semua</SelectItem>
                <SelectItem value="true">Diblokir</SelectItem>
                <SelectItem value="false">Tidak diblokir</SelectItem>
              </SelectContent>
            </Select>
          </div>
          {hasFilters ? (
            <Button
              variant="ghost"
              size="sm"
              onClick={() => updateParams({ tier: null, chatType: null, isActive: null, blocked: null })}
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
            {hasFilters ? "Tidak ada pengguna yang cocok dengan filter ini." : "Belum ada pengguna."}
          </p>
        ) : (
          <div className="overflow-hidden rounded-lg border border-border">
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>User hash</TableHead>
                  <TableHead>Tipe</TableHead>
                  <TableHead>Risk tier</TableHead>
                  <TableHead className="text-right">Skor</TableHead>
                  <TableHead className="text-right">Threat</TableHead>
                  <TableHead>Terakhir aktif</TableHead>
                  <TableHead>Status</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {data.items.map((item) => (
                  <TableRow
                    key={item.user_hash}
                    className="cursor-pointer"
                    onClick={() => router.push(`/users/${item.user_hash}`)}
                  >
                    <TableCell className="align-top font-mono text-xs text-muted-foreground">
                      {truncateHash(item.user_hash)}
                    </TableCell>
                    <TableCell className="align-top text-sm">{item.chat_type}</TableCell>
                    <TableCell className="align-top">
                      <Badge variant={tierVariant(item.tier)}>{item.tier}</Badge>
                    </TableCell>
                    <TableCell className="align-top text-right text-sm tabular-nums">{item.score}</TableCell>
                    <TableCell className="align-top text-right text-sm tabular-nums">{item.threat_count}</TableCell>
                    <TableCell className="align-top font-mono text-xs text-muted-foreground tabular-nums">
                      {item.last_seen ? new Date(item.last_seen).toLocaleString("id-ID") : "—"}
                    </TableCell>
                    <TableCell className="align-top">
                      {item.blocked ? (
                        <Badge variant="high">Diblokir</Badge>
                      ) : !item.is_active ? (
                        <Badge variant="outline">Nonaktif</Badge>
                      ) : (
                        <Badge variant="low">Aktif</Badge>
                      )}
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
    </Card>
  )
}
