"use client"

import * as React from "react"
import { usePathname, useRouter, useSearchParams } from "next/navigation"

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
import {
  api,
  GatewayError,
  type IncidentSeverity,
  type IncidentSummary,
  type Threats,
  type ThreatActionValue,
  type ThreatCategory,
  type ThreatRecord,
  type ThreatState,
} from "@/lib/api"

const PAGE_SIZE_OPTIONS = [10, 25, 50] as const
const DEFAULT_PAGE_SIZE = 25

const CATEGORIES: ThreatCategory[] = [
  "PHISHING",
  "SCAM",
  "SOCIAL_ENGINEERING",
  "MALICIOUS_LINK",
  "IMPERSONATION",
  "SPAM",
  "OTHER",
]

const STATES: ThreatState[] = ["DETECTED", "ANALYZED", "ACTIONED", "RESOLVED"]

const ACTIONS: { value: ThreatActionValue; label: string }[] = [
  { value: "ALLOW", label: "Allow — bukan ancaman" },
  { value: "WARN", label: "Warn — peringatkan pengguna" },
  { value: "BLOCK", label: "Block — blokir sesuai policy" },
  { value: "ESCALATE", label: "Escalate — naikkan ke incident/alert" },
  { value: "CONFIRM", label: "Confirm threat — klasifikasi AI benar" },
  { value: "FALSE_POSITIVE", label: "Mark false positive — koreksi klasifikasi" },
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

function stateVariant(state: ThreatState): "low" | "high" | "medium" | "unknown" {
  if (state === "RESOLVED") return "low"
  if (state === "ANALYZED") return "medium"
  return "unknown"
}

export function ThreatList() {
  return (
    <React.Suspense fallback={<ThreatListSkeleton />}>
      <ThreatListInner />
    </React.Suspense>
  )
}

function ThreatListSkeleton() {
  return (
    <Card>
      <CardHeader>
        <CardTitle>Threats</CardTitle>
        <CardDescription>Pesan yang terdeteksi HIGH/MEDIUM risk, siap ditriase operator.</CardDescription>
      </CardHeader>
      <CardContent className="flex flex-col gap-2">
        {Array.from({ length: 6 }).map((_, index) => (
          <Skeleton key={index} className="h-10 w-full" />
        ))}
      </CardContent>
    </Card>
  )
}

function ThreatListInner() {
  const router = useRouter()
  const pathname = usePathname()
  const searchParams = useSearchParams()

  const page = parsePage(searchParams.get("page"))
  const pageSize = parsePageSize(searchParams.get("pageSize"))
  const severity = searchParams.get("severity") ?? ""
  const category = searchParams.get("category") ?? ""
  const state = searchParams.get("state") ?? ""
  const action = searchParams.get("action") ?? ""
  const userHash = searchParams.get("userHash") ?? ""
  const offset = (page - 1) * pageSize

  const [data, setData] = React.useState<Threats | null>(null)
  const [loading, setLoading] = React.useState(true)
  const [error, setError] = React.useState<string | null>(null)
  const [actioning, setActioning] = React.useState<ThreatRecord | null>(null)
  const [linkingIncident, setLinkingIncident] = React.useState<ThreatRecord | null>(null)
  const [refreshKey, setRefreshKey] = React.useState(0)

  const hasFilters = Boolean(severity || category || state || action || userHash)

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
        const result = await api.threats(
          {
            limit: pageSize,
            offset,
            severity: severity ? (severity as "HIGH" | "MEDIUM") : undefined,
            category: category ? (category as ThreatCategory) : undefined,
            state: state ? (state as ThreatState) : undefined,
            action: action ? (action as ThreatActionValue) : undefined,
            userHash: userHash || undefined,
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
  }, [offset, pageSize, severity, category, state, action, userHash, refreshKey])

  const hasMore = data ? offset + data.items.length < data.total : false
  const totalPages = data && data.total > 0 ? Math.ceil(data.total / pageSize) : 1

  return (
    <Card>
      <CardHeader>
        <CardTitle>Threats</CardTitle>
        <CardDescription>Pesan yang terdeteksi HIGH/MEDIUM risk, siap ditriase operator.</CardDescription>
      </CardHeader>
      <CardContent className="flex flex-col gap-4">
        <div className="flex flex-wrap items-end gap-3">
          <FilterSelect
            label="Severity"
            value={severity}
            onChange={(value) => updateParams({ severity: value })}
            options={[
              { value: "HIGH", label: "HIGH" },
              { value: "MEDIUM", label: "MEDIUM" },
            ]}
          />
          <FilterSelect
            label="Kategori"
            value={category}
            onChange={(value) => updateParams({ category: value })}
            options={CATEGORIES.map((value) => ({ value, label: value }))}
          />
          <FilterSelect
            label="State"
            value={state}
            onChange={(value) => updateParams({ state: value })}
            options={STATES.map((value) => ({ value, label: value }))}
          />
          <FilterSelect
            label="Tindakan"
            value={action}
            onChange={(value) => updateParams({ action: value })}
            options={ACTIONS.map(({ value, label }) => ({ value, label: value, hint: label }))}
          />
          {userHash ? (
            <Badge variant="outline" className="gap-1.5">
              Pengguna: {userHash.slice(0, 8)}…
              <button
                type="button"
                className="text-muted-foreground hover:text-foreground"
                onClick={() => updateParams({ userHash: null })}
                aria-label="Hapus filter pengguna"
              >
                ×
              </button>
            </Badge>
          ) : null}
          {hasFilters ? (
            <Button
              variant="ghost"
              size="sm"
              onClick={() => updateParams({ severity: null, category: null, state: null, action: null, userHash: null })}
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
            {hasFilters ? "Tidak ada threat yang cocok dengan filter ini." : "Belum ada threat terdeteksi."}
          </p>
        ) : (
          <div className="overflow-hidden rounded-lg border border-border">
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead className="whitespace-nowrap">Waktu</TableHead>
                  <TableHead>Risiko</TableHead>
                  <TableHead>Kategori</TableHead>
                  <TableHead>State</TableHead>
                  <TableHead>Tindakan</TableHead>
                  <TableHead className="w-32">
                    <span className="sr-only">Aksi</span>
                  </TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {data.items.map((item) => (
                  <TableRow key={item.message_log_id}>
                    <TableCell className="align-top font-mono text-xs text-muted-foreground tabular-nums">
                      {new Date(item.at).toLocaleString("id-ID")}
                    </TableCell>
                    <TableCell className="align-top">
                      <Badge variant={riskVariant(item.risk)}>{item.risk}</Badge>
                    </TableCell>
                    <TableCell className="align-top text-sm">{item.threat_category}</TableCell>
                    <TableCell className="align-top">
                      <Badge variant={stateVariant(item.state)}>{item.state}</Badge>
                    </TableCell>
                    <TableCell className="min-w-40 align-top text-xs text-muted-foreground whitespace-normal">
                      {item.action ? (
                        <>
                          <span className="font-medium text-foreground">{item.action}</span>
                          {item.action_by ? ` oleh ${item.action_by}` : ""}
                          {item.notes ? ` · ${item.notes}` : ""}
                        </>
                      ) : (
                        "—"
                      )}
                    </TableCell>
                    <TableCell className="align-top">
                      <div className="flex flex-col gap-1.5">
                        <Button variant="outline" size="sm" onClick={() => setActioning(item)}>
                          {item.action ? "Ubah tindakan" : "Ambil tindakan"}
                        </Button>
                        <Button variant="ghost" size="sm" onClick={() => setLinkingIncident(item)}>
                          Tambah ke Incident
                        </Button>
                      </div>
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

      <ThreatActionDialog
        threat={actioning}
        onClose={() => setActioning(null)}
        onDone={() => {
          setActioning(null)
          setRefreshKey((key) => key + 1)
        }}
      />
      <LinkIncidentDialog threat={linkingIncident} onClose={() => setLinkingIncident(null)} />
    </Card>
  )
}

function FilterSelect({
  label,
  value,
  onChange,
  options,
}: {
  label: string
  value: string
  onChange: (value: string | null) => void
  options: { value: string; label: string; hint?: string }[]
}) {
  return (
    <div className="flex flex-col gap-1.5">
      <Label className="text-xs text-muted-foreground">{label}</Label>
      <Select value={value || "all"} onValueChange={(next) => onChange(next === "all" ? null : next)}>
        <SelectTrigger size="sm" className="h-8 w-[190px]">
          <SelectValue />
        </SelectTrigger>
        <SelectContent>
          <SelectItem value="all">Semua</SelectItem>
          {options.map((option) => (
            <SelectItem key={option.value} value={option.value}>
              {option.label}
            </SelectItem>
          ))}
        </SelectContent>
      </Select>
    </div>
  )
}

function ThreatActionDialog({
  threat,
  onClose,
  onDone,
}: {
  threat: ThreatRecord | null
  onClose: () => void
  onDone: () => void
}) {
  return (
    <Dialog open={threat !== null} onOpenChange={(open) => !open && onClose()}>
      <DialogContent>
        {/* Keyed by the threat: a different row clicked while the dialog is
            open remounts the form with fresh initial state, instead of an
            effect syncing state after the fact. */}
        {threat ? <ThreatActionForm key={threat.message_log_id} threat={threat} onClose={onClose} onDone={onDone} /> : null}
      </DialogContent>
    </Dialog>
  )
}

function ThreatActionForm({
  threat,
  onClose,
  onDone,
}: {
  threat: ThreatRecord
  onClose: () => void
  onDone: () => void
}) {
  const [action, setAction] = React.useState<ThreatActionValue | "">(threat.action ?? "")
  const [notes, setNotes] = React.useState(threat.notes ?? "")
  const [submitting, setSubmitting] = React.useState(false)
  const [error, setError] = React.useState<string | null>(null)

  async function submit() {
    if (!action) return
    setSubmitting(true)
    setError(null)
    try {
      await api.actionOnThreat(threat.message_log_id, action, notes)
      onDone()
    } catch (caught) {
      setError(caught instanceof GatewayError ? caught.message : "gagal menyimpan tindakan")
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <>
      <DialogHeader>
        <DialogTitle>Ambil tindakan</DialogTitle>
        <DialogDescription>
          Setiap tindakan menutup threat ini dan tercatat di Audit Log. Confirm/False positive masuk
          antrean feedback — tidak langsung mengubah model.
        </DialogDescription>
      </DialogHeader>

      <div className="flex flex-col gap-3">
        <div className="flex flex-col gap-1.5">
          <Label className="text-xs text-muted-foreground">Tindakan</Label>
          <Select value={action} onValueChange={(value) => setAction(value as ThreatActionValue)}>
            <SelectTrigger className="w-full">
              <SelectValue placeholder="Pilih tindakan" />
            </SelectTrigger>
            <SelectContent>
              {ACTIONS.map((option) => (
                <SelectItem key={option.value} value={option.value}>
                  {option.label}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </div>
        <div className="flex flex-col gap-1.5">
          <Label className="text-xs text-muted-foreground">Catatan (opsional)</Label>
          <Textarea
            value={notes}
            onChange={(event) => setNotes(event.target.value)}
            placeholder="Alasan atau konteks tambahan…"
            rows={3}
          />
        </div>
        {error ? <p className="text-sm text-destructive">{error}</p> : null}
      </div>

      <DialogFooter>
        <Button variant="outline" onClick={onClose} disabled={submitting}>
          Batal
        </Button>
        <Button onClick={submit} disabled={!action || submitting}>
          {submitting ? "Menyimpan…" : "Simpan tindakan"}
        </Button>
      </DialogFooter>
    </>
  )
}

const INCIDENT_SEVERITIES: IncidentSeverity[] = ["LOW", "MEDIUM", "HIGH", "CRITICAL"]
const OPEN_INCIDENT_STATES = new Set(["OPEN", "INVESTIGATING", "CONTAINED"])

function LinkIncidentDialog({ threat, onClose }: { threat: ThreatRecord | null; onClose: () => void }) {
  return (
    <Dialog open={threat !== null} onOpenChange={(open) => !open && onClose()}>
      <DialogContent>
        {threat ? <LinkIncidentForm key={threat.message_log_id} threat={threat} onClose={onClose} /> : null}
      </DialogContent>
    </Dialog>
  )
}

function LinkIncidentForm({ threat, onClose }: { threat: ThreatRecord; onClose: () => void }) {
  const [openIncidents, setOpenIncidents] = React.useState<IncidentSummary[] | null>(null)
  const [target, setTarget] = React.useState<"new" | string>("new")
  const [title, setTitle] = React.useState("")
  const [severity, setSeverity] = React.useState<IncidentSeverity | "">("")
  const [submitting, setSubmitting] = React.useState(false)
  const [done, setDone] = React.useState(false)
  const [error, setError] = React.useState<string | null>(null)

  React.useEffect(() => {
    let cancelled = false
    api
      .incidents({ limit: 50 })
      .then((result) => {
        if (cancelled) return
        setOpenIncidents(result.available ? result.items.filter((i) => OPEN_INCIDENT_STATES.has(i.state)) : [])
      })
      .catch(() => {
        if (!cancelled) setOpenIncidents([])
      })
    return () => {
      cancelled = true
    }
  }, [])

  async function submit() {
    setSubmitting(true)
    setError(null)
    try {
      if (target === "new") {
        if (!title.trim() || !severity) return
        await api.createIncident(title, severity, [threat.message_log_id])
      } else {
        await api.addThreatToIncident(target, threat.message_log_id)
      }
      setDone(true)
    } catch (caught) {
      setError(caught instanceof GatewayError ? caught.message : "gagal menambahkan ke incident")
    } finally {
      setSubmitting(false)
    }
  }

  const canSubmit = target === "new" ? Boolean(title.trim() && severity) : true

  return (
    <>
      <DialogHeader>
        <DialogTitle>Tambah ke Incident</DialogTitle>
        <DialogDescription>Kelompokkan threat ini ke incident baru atau incident yang sudah ada.</DialogDescription>
      </DialogHeader>

      {done ? (
        <p className="text-sm text-muted-foreground">Berhasil ditambahkan.</p>
      ) : (
        <div className="flex flex-col gap-3">
          <div className="flex flex-col gap-1.5">
            <Label className="text-xs text-muted-foreground">Incident</Label>
            <Select value={target} onValueChange={(value) => setTarget(value ?? "new")}>
              <SelectTrigger className="w-full">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="new">Buat incident baru</SelectItem>
                {(openIncidents ?? []).map((incident) => (
                  <SelectItem key={incident.id} value={incident.id}>
                    {incident.code} — {incident.title}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
            {openIncidents !== null && openIncidents.length === 0 ? (
              <p className="text-xs text-muted-foreground">Belum ada incident yang masih terbuka.</p>
            ) : null}
          </div>

          {target === "new" ? (
            <>
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
                    {INCIDENT_SEVERITIES.map((value) => (
                      <SelectItem key={value} value={value}>
                        {value}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </div>
            </>
          ) : null}
          {error ? <p className="text-sm text-destructive">{error}</p> : null}
        </div>
      )}

      <DialogFooter>
        <Button variant="outline" onClick={onClose}>
          {done ? "Tutup" : "Batal"}
        </Button>
        {!done ? (
          <Button onClick={submit} disabled={!canSubmit || submitting}>
            {submitting ? "Menyimpan…" : "Tambahkan"}
          </Button>
        ) : null}
      </DialogFooter>
    </>
  )
}
