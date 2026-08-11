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
import { Textarea } from "@/components/ui/textarea"
import { toast } from "@/components/ui/toast"
import {
  api,
  GatewayError,
  type DetectionRuleItem,
  type DetectionRules,
  type DetectionRuleSeverity,
  type DetectionRuleStatus,
  type DetectionRuleType,
} from "@/lib/api"

const PAGE_SIZE_OPTIONS = [10, 25, 50] as const
const DEFAULT_PAGE_SIZE = 25

const RULE_TYPES: DetectionRuleType[] = [
  "KEYWORD",
  "DOMAIN",
  "URL",
  "RISK_THRESHOLD",
  "PATTERN",
  "REPEATED_OFFENDER",
  "RATE_LIMIT",
  "ALLOWLIST",
  "BLOCKLIST",
]
const RULE_TYPE_LABELS: Record<DetectionRuleType, string> = {
  KEYWORD: "Keyword",
  DOMAIN: "Domain",
  URL: "URL",
  RISK_THRESHOLD: "Risk threshold",
  PATTERN: "Pattern detection",
  REPEATED_OFFENDER: "Repeated offender",
  RATE_LIMIT: "Rate limiting",
  ALLOWLIST: "Allowlist",
  BLOCKLIST: "Blocklist",
}
const SEVERITIES: DetectionRuleSeverity[] = ["HIGH", "MEDIUM", "LOW"]
const STATUSES: DetectionRuleStatus[] = ["DRAFT", "ACTIVE", "DISABLED", "ARCHIVED"]

// Rule types whose condition is a line-separated list of strings.
const LIST_VALUE_TYPES = new Set<DetectionRuleType>(["KEYWORD", "DOMAIN", "URL", "ALLOWLIST", "BLOCKLIST"])

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

function severityVariant(severity: DetectionRuleSeverity): BadgeVariant {
  if (severity === "HIGH") return "high"
  if (severity === "MEDIUM") return "medium"
  return "low"
}

function statusVariant(status: DetectionRuleStatus): BadgeVariant {
  if (status === "ACTIVE") return "low"
  if (status === "DRAFT") return "medium"
  if (status === "DISABLED") return "unknown"
  return "outline"
}

function conditionSummary(rule: DetectionRuleItem): string {
  const c = rule.condition
  if (LIST_VALUE_TYPES.has(rule.rule_type)) {
    const values = Array.isArray(c.values) ? (c.values as unknown[]) : []
    return values.join(", ")
  }
  if (rule.rule_type === "RISK_THRESHOLD") return `threshold ≥ ${c.threshold}`
  if (rule.rule_type === "PATTERN") {
    const components = Array.isArray(c.components) ? (c.components as unknown[]) : []
    return components.join(" + ")
  }
  if (rule.rule_type === "REPEATED_OFFENDER") return `${c.occurrences}× dalam ${c.window_hours} jam`
  if (rule.rule_type === "RATE_LIMIT") return `${c.max_messages} pesan / ${c.window_minutes} menit`
  return JSON.stringify(c)
}

export function DetectionRuleList() {
  return (
    <React.Suspense fallback={<DetectionRuleListSkeleton />}>
      <DetectionRuleListInner />
    </React.Suspense>
  )
}

function DetectionRuleListSkeleton() {
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

function DetectionRuleListInner() {
  const router = useRouter()
  const pathname = usePathname()
  const searchParams = useSearchParams()

  const page = parsePage(searchParams.get("page"))
  const pageSize = parsePageSize(searchParams.get("pageSize"))
  const ruleType = searchParams.get("ruleType") ?? ""
  const status = searchParams.get("status") ?? ""
  const severity = searchParams.get("severity") ?? ""
  const offset = (page - 1) * pageSize

  const [data, setData] = React.useState<DetectionRules | null>(null)
  const [loading, setLoading] = React.useState(true)
  const [error, setError] = React.useState<string | null>(null)
  const [pendingId, setPendingId] = React.useState<string | null>(null)
  const [editing, setEditing] = React.useState<DetectionRuleItem | "new" | null>(null)
  const [refreshKey, setRefreshKey] = React.useState(0)

  const hasFilters = Boolean(ruleType || status || severity)

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
        const result = await api.detectionRules(
          {
            limit: pageSize,
            offset,
            ruleType: (ruleType as DetectionRuleType) || undefined,
            status: (status as DetectionRuleStatus) || undefined,
            severity: (severity as DetectionRuleSeverity) || undefined,
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
  }, [offset, pageSize, ruleType, status, severity, refreshKey])

  async function statusAction(rule: DetectionRuleItem, action: "ACTIVATE" | "DISABLE" | "ARCHIVE") {
    setPendingId(rule.id)
    try {
      await api.actionOnDetectionRule(rule.id, action)
      setRefreshKey((key) => key + 1)
      const label = action === "ACTIVATE" ? "diaktifkan" : action === "DISABLE" ? "dinonaktifkan" : "diarsipkan"
      toast.success(`Rule ${label}`, { description: rule.name })
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
          Buat Rule
        </Button>
      </CardHeader>
      <CardContent className="flex flex-col gap-4">
        <div className="flex flex-wrap items-end gap-3">
          <div className="flex flex-col gap-1.5">
            <Label className="text-xs text-muted-foreground">Jenis</Label>
            <Select value={ruleType || "all"} onValueChange={(v) => updateParams({ ruleType: v === "all" ? null : v })}>
              <SelectTrigger size="sm" className="h-8 w-[170px]">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="all">Semua</SelectItem>
                {RULE_TYPES.map((value) => (
                  <SelectItem key={value} value={value}>
                    {RULE_TYPE_LABELS[value]}
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
            <Label className="text-xs text-muted-foreground">Severity</Label>
            <Select value={severity || "all"} onValueChange={(v) => updateParams({ severity: v === "all" ? null : v })}>
              <SelectTrigger size="sm" className="h-8 w-[140px]">
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
          {hasFilters ? (
            <Button variant="ghost" size="sm" onClick={() => updateParams({ ruleType: null, status: null, severity: null })}>
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
            {hasFilters ? "Tidak ada rule yang cocok dengan filter ini." : "Belum ada rule."}
          </p>
        ) : (
          <div className="overflow-hidden rounded-lg border border-border">
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>Nama</TableHead>
                  <TableHead>Jenis</TableHead>
                  <TableHead>Kondisi</TableHead>
                  <TableHead>Severity</TableHead>
                  <TableHead>Status</TableHead>
                  <TableHead className="w-56">
                    <span className="sr-only">Aksi</span>
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
                        {RULE_TYPE_LABELS[item.rule_type]}
                      </TableCell>
                      <TableCell className="min-w-48 align-top text-xs text-muted-foreground">
                        {conditionSummary(item)}
                      </TableCell>
                      <TableCell className="align-top">
                        <Badge variant={severityVariant(item.severity)}>{item.severity}</Badge>
                      </TableCell>
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

      <RuleDialog
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
// Create / edit dialog — condition fields switch by rule_type.
// --------------------------------------------------------------------------

type ConditionFormState = {
  listValues: string
  threshold: string
  components: string
  occurrences: string
  windowHours: string
  maxMessages: string
  windowMinutes: string
}

function emptyConditionForm(): ConditionFormState {
  return {
    listValues: "",
    threshold: "50",
    components: "",
    occurrences: "3",
    windowHours: "24",
    maxMessages: "20",
    windowMinutes: "10",
  }
}

function conditionToFormState(ruleType: DetectionRuleType, condition: Record<string, unknown>): ConditionFormState {
  const form = emptyConditionForm()
  if (LIST_VALUE_TYPES.has(ruleType) && Array.isArray(condition.values)) {
    form.listValues = (condition.values as unknown[]).join("\n")
  } else if (ruleType === "PATTERN" && Array.isArray(condition.components)) {
    form.components = (condition.components as unknown[]).join("\n")
  } else if (ruleType === "RISK_THRESHOLD" && condition.threshold !== undefined) {
    form.threshold = String(condition.threshold)
  } else if (ruleType === "REPEATED_OFFENDER") {
    if (condition.occurrences !== undefined) form.occurrences = String(condition.occurrences)
    if (condition.window_hours !== undefined) form.windowHours = String(condition.window_hours)
  } else if (ruleType === "RATE_LIMIT") {
    if (condition.max_messages !== undefined) form.maxMessages = String(condition.max_messages)
    if (condition.window_minutes !== undefined) form.windowMinutes = String(condition.window_minutes)
  }
  return form
}

function formStateToCondition(ruleType: DetectionRuleType, form: ConditionFormState): Record<string, unknown> {
  if (LIST_VALUE_TYPES.has(ruleType)) {
    return { values: form.listValues.split("\n").map((v) => v.trim()).filter(Boolean) }
  }
  if (ruleType === "PATTERN") {
    return { components: form.components.split("\n").map((v) => v.trim()).filter(Boolean) }
  }
  if (ruleType === "RISK_THRESHOLD") {
    return { threshold: Number(form.threshold) }
  }
  if (ruleType === "REPEATED_OFFENDER") {
    return { occurrences: Number(form.occurrences), window_hours: Number(form.windowHours) }
  }
  return { max_messages: Number(form.maxMessages), window_minutes: Number(form.windowMinutes) }
}

function RuleDialog({
  target,
  onClose,
  onDone,
}: {
  target: DetectionRuleItem | "new" | null
  onClose: () => void
  onDone: () => void
}) {
  return (
    <Dialog open={target !== null} onOpenChange={(open) => !open && onClose()}>
      <DialogContent className="sm:max-w-lg">
        {target ? (
          <RuleForm key={target === "new" ? "new" : target.id} target={target} onClose={onClose} onDone={onDone} />
        ) : null}
      </DialogContent>
    </Dialog>
  )
}

function RuleForm({
  target,
  onClose,
  onDone,
}: {
  target: DetectionRuleItem | "new"
  onClose: () => void
  onDone: () => void
}) {
  const isNew = target === "new"
  const [name, setName] = React.useState(isNew ? "" : target.name)
  const [ruleType, setRuleType] = React.useState<DetectionRuleType>(isNew ? "KEYWORD" : target.rule_type)
  const [severity, setSeverity] = React.useState<DetectionRuleSeverity>(isNew ? "MEDIUM" : target.severity)
  const [condition, setCondition] = React.useState<ConditionFormState>(
    isNew ? emptyConditionForm() : conditionToFormState(target.rule_type, target.condition),
  )
  const [submitting, setSubmitting] = React.useState(false)
  const [error, setError] = React.useState<string | null>(null)

  async function submit() {
    if (!name.trim()) return
    setSubmitting(true)
    setError(null)
    try {
      if (isNew) {
        await api.createDetectionRule(name.trim(), ruleType, formStateToCondition(ruleType, condition), severity)
      } else {
        await api.actionOnDetectionRule(target.id, "UPDATE", {
          name: name.trim(),
          condition: formStateToCondition(ruleType, condition),
          severity,
        })
      }
      onDone()
      toast.success(isNew ? "Rule dibuat" : "Rule diperbarui", { description: name.trim() })
    } catch (caught) {
      setError(caught instanceof GatewayError ? caught.message : "gagal menyimpan rule")
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <>
      <DialogHeader>
        <DialogTitle>{isNew ? "Buat Detection Rule" : "Edit Detection Rule"}</DialogTitle>
        <DialogDescription>
          Rule deterministik — bisa diubah tanpa retraining model. Setiap perubahan tercatat di Audit Log.
        </DialogDescription>
      </DialogHeader>

      <div className="flex flex-col gap-3">
        <div className="flex flex-col gap-1.5">
          <Label className="text-xs text-muted-foreground">Nama</Label>
          <Input value={name} onChange={(event) => setName(event.target.value)} placeholder="mis. Blokir domain penipuan" />
        </div>

        <div className="grid grid-cols-2 gap-3">
          <div className="flex flex-col gap-1.5">
            <Label className="text-xs text-muted-foreground">Jenis</Label>
            <Select
              value={ruleType}
              onValueChange={(v) => setRuleType(v as DetectionRuleType)}
              disabled={!isNew}
            >
              <SelectTrigger className="h-9 w-full">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                {RULE_TYPES.map((value) => (
                  <SelectItem key={value} value={value}>
                    {RULE_TYPE_LABELS[value]}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>
          <div className="flex flex-col gap-1.5">
            <Label className="text-xs text-muted-foreground">Severity</Label>
            <Select value={severity} onValueChange={(v) => setSeverity(v as DetectionRuleSeverity)}>
              <SelectTrigger className="h-9 w-full">
                <SelectValue />
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
        </div>

        <ConditionFields ruleType={ruleType} value={condition} onChange={setCondition} />

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
  ruleType,
  value,
  onChange,
}: {
  ruleType: DetectionRuleType
  value: ConditionFormState
  onChange: (next: ConditionFormState) => void
}) {
  function set(partial: Partial<ConditionFormState>) {
    onChange({ ...value, ...partial })
  }

  if (LIST_VALUE_TYPES.has(ruleType)) {
    return (
      <div className="flex flex-col gap-1.5">
        <Label className="text-xs text-muted-foreground">Nilai (satu per baris)</Label>
        <Textarea
          value={value.listValues}
          onChange={(event) => set({ listValues: event.target.value })}
          placeholder={ruleType === "DOMAIN" ? "scam-bank.example" : ruleType === "URL" ? "bit.ly/*" : "arisan bodong"}
          rows={4}
        />
      </div>
    )
  }

  if (ruleType === "RISK_THRESHOLD") {
    return (
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
    )
  }

  if (ruleType === "PATTERN") {
    return (
      <div className="flex flex-col gap-1.5">
        <Label className="text-xs text-muted-foreground">Komponen pola (satu per baris)</Label>
        <Textarea
          value={value.components}
          onChange={(event) => set({ components: event.target.value })}
          placeholder={"nomor_rekening\nurgensi\ntautan"}
          rows={3}
        />
      </div>
    )
  }

  if (ruleType === "REPEATED_OFFENDER") {
    return (
      <div className="grid grid-cols-2 gap-3">
        <div className="flex flex-col gap-1.5">
          <Label className="text-xs text-muted-foreground">Jumlah kejadian (≥2)</Label>
          <Input
            type="number"
            min={2}
            value={value.occurrences}
            onChange={(event) => set({ occurrences: event.target.value })}
          />
        </div>
        <div className="flex flex-col gap-1.5">
          <Label className="text-xs text-muted-foreground">Jendela waktu (jam)</Label>
          <Input
            type="number"
            min={1}
            value={value.windowHours}
            onChange={(event) => set({ windowHours: event.target.value })}
          />
        </div>
      </div>
    )
  }

  // RATE_LIMIT
  return (
    <div className="grid grid-cols-2 gap-3">
      <div className="flex flex-col gap-1.5">
        <Label className="text-xs text-muted-foreground">Maks. pesan</Label>
        <Input
          type="number"
          min={1}
          value={value.maxMessages}
          onChange={(event) => set({ maxMessages: event.target.value })}
        />
      </div>
      <div className="flex flex-col gap-1.5">
        <Label className="text-xs text-muted-foreground">Jendela waktu (menit)</Label>
        <Input
          type="number"
          min={1}
          value={value.windowMinutes}
          onChange={(event) => set({ windowMinutes: event.target.value })}
        />
      </div>
    </div>
  )
}
