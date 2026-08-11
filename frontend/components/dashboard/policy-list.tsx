"use client"

import * as React from "react"
import { usePathname, useRouter, useSearchParams } from "next/navigation"

import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Card, CardContent, CardHeader } from "@/components/ui/card"
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
import { toast } from "@/components/ui/toast"
import {
  api,
  GatewayError,
  type PolicyAction,
  type PolicyItem,
  type Policies,
  type PolicyScope,
  type PolicyStatus,
  type ThreatCategory,
} from "@/lib/api"

const PAGE_SIZE_OPTIONS = [10, 25, 50] as const
const DEFAULT_PAGE_SIZE = 25

const SCOPES: PolicyScope[] = ["DEFAULT", "CATEGORY_THRESHOLD", "USER_SPECIFIC"]
const SCOPE_LABELS: Record<PolicyScope, string> = {
  DEFAULT: "Default (fallback)",
  CATEGORY_THRESHOLD: "Kategori + threshold",
  USER_SPECIFIC: "User spesifik",
}
const ACTIONS: PolicyAction[] = ["ALLOW", "WARN", "BLOCK", "ALERT", "ESCALATE"]
const STATUSES: PolicyStatus[] = ["DRAFT", "ACTIVE", "DISABLED", "ARCHIVED"]
const THREAT_CATEGORIES: ThreatCategory[] = [
  "PHISHING",
  "SCAM",
  "SOCIAL_ENGINEERING",
  "MALICIOUS_LINK",
  "IMPERSONATION",
  "SPAM",
  "OTHER",
]

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

type BadgeVariant = "default" | "outline" | "high" | "medium" | "low" | "unknown"

function actionVariant(action: PolicyAction): BadgeVariant {
  if (action === "BLOCK") return "high"
  if (action === "ESCALATE") return "high"
  if (action === "ALERT") return "medium"
  if (action === "WARN") return "medium"
  return "low"
}

function statusVariant(status: PolicyStatus): BadgeVariant {
  if (status === "ACTIVE") return "low"
  if (status === "DRAFT") return "medium"
  if (status === "DISABLED") return "unknown"
  return "outline"
}

function conditionSummary(policy: PolicyItem): string {
  const c = policy.condition
  if (policy.scope === "DEFAULT") return "— (fallback, tanpa kondisi)"
  if (policy.scope === "CATEGORY_THRESHOLD") return `${c.threat_category} · threshold ≥ ${c.threshold}`
  if (policy.scope === "USER_SPECIFIC") return `user_hash: ${String(c.user_hash).slice(0, 16)}…`
  return JSON.stringify(c)
}

export function PolicyList() {
  return (
    <React.Suspense fallback={<PolicyListSkeleton />}>
      <PolicyListInner />
    </React.Suspense>
  )
}

function PolicyListSkeleton() {
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

function PolicyListInner() {
  const router = useRouter()
  const pathname = usePathname()
  const searchParams = useSearchParams()

  const page = parsePage(searchParams.get("page"))
  const pageSize = parsePageSize(searchParams.get("pageSize"))
  const scope = searchParams.get("scope") ?? ""
  const status = searchParams.get("status") ?? ""
  const action = searchParams.get("action") ?? ""
  const offset = (page - 1) * pageSize

  const [data, setData] = React.useState<Policies | null>(null)
  const [loading, setLoading] = React.useState(true)
  const [error, setError] = React.useState<string | null>(null)
  const [pendingId, setPendingId] = React.useState<string | null>(null)
  const [editing, setEditing] = React.useState<PolicyItem | "new" | null>(null)
  const [refreshKey, setRefreshKey] = React.useState(0)

  const hasFilters = Boolean(scope || status || action)

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
        const result = await api.policies(
          {
            limit: pageSize,
            offset,
            scope: (scope as PolicyScope) || undefined,
            status: (status as PolicyStatus) || undefined,
            action: (action as PolicyAction) || undefined,
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
  }, [offset, pageSize, scope, status, action, refreshKey])

  async function statusAction(policy: PolicyItem, operation: "ACTIVATE" | "DISABLE" | "ARCHIVE") {
    setPendingId(policy.id)
    try {
      await api.actionOnPolicy(policy.id, operation)
      setRefreshKey((key) => key + 1)
      const label =
        operation === "ACTIVATE" ? "diaktifkan" : operation === "DISABLE" ? "dinonaktifkan" : "diarsipkan"
      toast.success(`Policy ${label}`, { description: policy.name })
    } catch {
      // Row stays as-is; the refetch above on the next successful action keeps state consistent.
    } finally {
      setPendingId(null)
    }
  }

  const hasMore = data ? offset + data.items.length < data.total : false
  const totalPages = data && data.total > 0 ? Math.ceil(data.total / pageSize) : 1

  return (
    <Card>
      <CardHeader className="flex-row justify-end">
        <Button size="sm" onClick={() => setEditing("new")}>
          Buat Policy
        </Button>
      </CardHeader>
      <CardContent className="flex flex-col gap-4">
        <div className="flex flex-wrap items-end gap-3">
          <div className="flex flex-col gap-1.5">
            <Label className="text-xs text-muted-foreground">Scope</Label>
            <Select value={scope || "all"} onValueChange={(v) => updateParams({ scope: v === "all" ? null : v })}>
              <SelectTrigger size="sm" className="h-8 w-[180px]">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="all">Semua</SelectItem>
                {SCOPES.map((value) => (
                  <SelectItem key={value} value={value}>
                    {SCOPE_LABELS[value]}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>
          <div className="flex flex-col gap-1.5">
            <Label className="text-xs text-muted-foreground">Status</Label>
            <Select value={status || "all"} onValueChange={(v) => updateParams({ status: v === "all" ? null : v })}>
              <SelectTrigger size="sm" className="h-8 w-[140px]">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="all">Semua</SelectItem>
                {STATUSES.map((value) => (
                  <SelectItem key={value} value={value}>
                    {value}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>
          <div className="flex flex-col gap-1.5">
            <Label className="text-xs text-muted-foreground">Aksi</Label>
            <Select value={action || "all"} onValueChange={(v) => updateParams({ action: v === "all" ? null : v })}>
              <SelectTrigger size="sm" className="h-8 w-[140px]">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="all">Semua</SelectItem>
                {ACTIONS.map((value) => (
                  <SelectItem key={value} value={value}>
                    {value}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>
          {hasFilters ? (
            <Button variant="ghost" size="sm" onClick={() => updateParams({ scope: null, status: null, action: null })}>
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
            {hasFilters ? "Tidak ada policy yang cocok dengan filter ini." : "Belum ada policy."}
          </p>
        ) : (
          <div className="overflow-hidden rounded-lg border border-border">
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>Nama</TableHead>
                  <TableHead>Scope</TableHead>
                  <TableHead>Kondisi</TableHead>
                  <TableHead>Aksi</TableHead>
                  <TableHead>Prioritas</TableHead>
                  <TableHead>Status</TableHead>
                  <TableHead className="w-56">
                    <span className="sr-only">Kelola</span>
                  </TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {data.items.map((item) => {
                  const isPending = pendingId === item.id
                  return (
                    <TableRow key={item.id}>
                      <TableCell className="min-w-40 align-top text-sm font-medium">{item.name}</TableCell>
                      <TableCell className="align-top text-xs text-muted-foreground">
                        {SCOPE_LABELS[item.scope]}
                      </TableCell>
                      <TableCell className="min-w-48 align-top text-xs text-muted-foreground">
                        {conditionSummary(item)}
                      </TableCell>
                      <TableCell className="align-top">
                        <Badge variant={actionVariant(item.action)}>{item.action}</Badge>
                      </TableCell>
                      <TableCell className="align-top text-xs text-muted-foreground">{item.priority}</TableCell>
                      <TableCell className="align-top">
                        <Badge variant={statusVariant(item.status)}>{item.status}</Badge>
                      </TableCell>
                      <TableCell className="align-top">
                        <div className="flex flex-wrap gap-1.5">
                          <Button
                            variant="outline"
                            size="sm"
                            disabled={item.status === "ARCHIVED" || isPending}
                            onClick={() => setEditing(item)}
                          >
                            Edit
                          </Button>
                          {item.status === "ACTIVE" ? (
                            <Button
                              variant="outline"
                              size="sm"
                              disabled={isPending}
                              onClick={() => statusAction(item, "DISABLE")}
                            >
                              Nonaktifkan
                            </Button>
                          ) : item.status === "DRAFT" || item.status === "DISABLED" ? (
                            <Button
                              variant="outline"
                              size="sm"
                              disabled={isPending}
                              onClick={() => statusAction(item, "ACTIVATE")}
                            >
                              Aktifkan
                            </Button>
                          ) : null}
                          {item.status !== "ARCHIVED" ? (
                            <Button
                              variant="outline"
                              size="sm"
                              disabled={isPending}
                              onClick={() => statusAction(item, "ARCHIVE")}
                            >
                              Archive
                            </Button>
                          ) : null}
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

      <PolicyDialog
        target={editing}
        onClose={() => setEditing(null)}
        onDone={() => {
          setEditing(null)
          setRefreshKey((key) => key + 1)
        }}
      />
    </Card>
  )
}

// --------------------------------------------------------------------------
// Create / edit dialog — condition fields switch by scope.
// --------------------------------------------------------------------------

type ConditionFormState = {
  threatCategory: ThreatCategory
  threshold: string
  userHash: string
}

function emptyConditionForm(): ConditionFormState {
  return { threatCategory: "SCAM", threshold: "50", userHash: "" }
}

function conditionToFormState(scope: PolicyScope, condition: Record<string, unknown>): ConditionFormState {
  const form = emptyConditionForm()
  if (scope === "CATEGORY_THRESHOLD") {
    if (typeof condition.threat_category === "string") form.threatCategory = condition.threat_category as ThreatCategory
    if (condition.threshold !== undefined) form.threshold = String(condition.threshold)
  } else if (scope === "USER_SPECIFIC" && typeof condition.user_hash === "string") {
    form.userHash = condition.user_hash
  }
  return form
}

function formStateToCondition(scope: PolicyScope, form: ConditionFormState): Record<string, unknown> {
  if (scope === "DEFAULT") return {}
  if (scope === "CATEGORY_THRESHOLD") {
    return { threat_category: form.threatCategory, threshold: Number(form.threshold) }
  }
  return { user_hash: form.userHash.trim() }
}

function PolicyDialog({
  target,
  onClose,
  onDone,
}: {
  target: PolicyItem | "new" | null
  onClose: () => void
  onDone: () => void
}) {
  return (
    <Dialog open={target !== null} onOpenChange={(open) => !open && onClose()}>
      <DialogContent className="sm:max-w-lg">
        {target ? (
          <PolicyForm key={target === "new" ? "new" : target.id} target={target} onClose={onClose} onDone={onDone} />
        ) : null}
      </DialogContent>
    </Dialog>
  )
}

function PolicyForm({
  target,
  onClose,
  onDone,
}: {
  target: PolicyItem | "new"
  onClose: () => void
  onDone: () => void
}) {
  const isNew = target === "new"
  const [name, setName] = React.useState(isNew ? "" : target.name)
  const [scope, setScope] = React.useState<PolicyScope>(isNew ? "CATEGORY_THRESHOLD" : target.scope)
  const [action, setAction] = React.useState<PolicyAction>(isNew ? "BLOCK" : target.action)
  const [priority, setPriority] = React.useState(isNew ? "100" : String(target.priority))
  const [condition, setCondition] = React.useState<ConditionFormState>(
    isNew ? emptyConditionForm() : conditionToFormState(target.scope, target.condition),
  )
  const [submitting, setSubmitting] = React.useState(false)
  const [error, setError] = React.useState<string | null>(null)

  async function submit() {
    if (!name.trim()) return
    setSubmitting(true)
    setError(null)
    try {
      const conditionPayload = formStateToCondition(scope, condition)
      const priorityValue = Number(priority)
      if (isNew) {
        await api.createPolicy(name.trim(), scope, conditionPayload, action, priorityValue)
      } else {
        await api.actionOnPolicy(target.id, "UPDATE", {
          name: name.trim(),
          condition: conditionPayload,
          action,
          priority: priorityValue,
        })
      }
      onDone()
      toast.success(isNew ? "Policy dibuat" : "Policy diperbarui", { description: name.trim() })
    } catch (caught) {
      setError(caught instanceof GatewayError ? caught.message : "gagal menyimpan policy")
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <>
      <DialogHeader>
        <DialogTitle>{isNew ? "Buat Security Policy" : "Edit Security Policy"}</DialogTitle>
        <DialogDescription>
          IF kondisi THEN aksi. Policy baru selalu mulai sebagai DRAFT. Setiap perubahan tercatat di Audit Log.
        </DialogDescription>
      </DialogHeader>

      <div className="flex flex-col gap-3">
        <div className="flex flex-col gap-1.5">
          <Label className="text-xs text-muted-foreground">Nama</Label>
          <Input value={name} onChange={(event) => setName(event.target.value)} placeholder="mis. Blokir scam risiko tinggi" />
        </div>

        <div className="grid grid-cols-2 gap-3">
          <div className="flex flex-col gap-1.5">
            <Label className="text-xs text-muted-foreground">Scope</Label>
            <Select value={scope} onValueChange={(v) => setScope(v as PolicyScope)} disabled={!isNew}>
              <SelectTrigger className="h-9 w-full">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                {SCOPES.map((value) => (
                  <SelectItem key={value} value={value}>
                    {SCOPE_LABELS[value]}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>
          <div className="flex flex-col gap-1.5">
            <Label className="text-xs text-muted-foreground">Aksi</Label>
            <Select value={action} onValueChange={(v) => setAction(v as PolicyAction)}>
              <SelectTrigger className="h-9 w-full">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                {ACTIONS.map((value) => (
                  <SelectItem key={value} value={value}>
                    {value}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>
        </div>

        <div className="flex flex-col gap-1.5">
          <Label className="text-xs text-muted-foreground">Prioritas (angka lebih kecil dievaluasi lebih dulu)</Label>
          <Input type="number" value={priority} onChange={(event) => setPriority(event.target.value)} />
        </div>

        <ConditionFields scope={scope} value={condition} onChange={setCondition} />

        {error ? <p className="text-sm text-destructive">{error}</p> : null}
      </div>

      <DialogFooter>
        <Button variant="outline" onClick={onClose} disabled={submitting}>
          Batal
        </Button>
        <Button onClick={submit} disabled={!name.trim() || submitting}>
          {submitting ? "Menyimpan…" : isNew ? "Buat" : "Simpan"}
        </Button>
      </DialogFooter>
    </>
  )
}

function ConditionFields({
  scope,
  value,
  onChange,
}: {
  scope: PolicyScope
  value: ConditionFormState
  onChange: (next: ConditionFormState) => void
}) {
  function set(partial: Partial<ConditionFormState>) {
    onChange({ ...value, ...partial })
  }

  if (scope === "DEFAULT") {
    return (
      <p className="text-xs text-muted-foreground">
        Policy default tidak punya kondisi — berlaku sebagai fallback saat tidak ada policy lain yang cocok.
      </p>
    )
  }

  if (scope === "CATEGORY_THRESHOLD") {
    return (
      <div className="grid grid-cols-2 gap-3">
        <div className="flex flex-col gap-1.5">
          <Label className="text-xs text-muted-foreground">Kategori ancaman</Label>
          <Select value={value.threatCategory} onValueChange={(v) => set({ threatCategory: v as ThreatCategory })}>
            <SelectTrigger className="h-9 w-full">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              {THREAT_CATEGORIES.map((category) => (
                <SelectItem key={category} value={category}>
                  {category}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </div>
        <div className="flex flex-col gap-1.5">
          <Label className="text-xs text-muted-foreground">Threshold (0–100)</Label>
          <Input
            type="number"
            min={0}
            max={100}
            value={value.threshold}
            onChange={(event) => set({ threshold: event.target.value })}
          />
        </div>
      </div>
    )
  }

  // USER_SPECIFIC
  return (
    <div className="flex flex-col gap-1.5">
      <Label className="text-xs text-muted-foreground">User hash</Label>
      <Input
        value={value.userHash}
        onChange={(event) => set({ userHash: event.target.value })}
        placeholder="hash SHA-256 dari /users"
      />
    </div>
  )
}
