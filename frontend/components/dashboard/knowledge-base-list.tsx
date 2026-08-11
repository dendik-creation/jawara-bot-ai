"use client"

import * as React from "react"
import { usePathname, useRouter, useSearchParams } from "next/navigation"

import { Badge } from "@/components/ui/badge"
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
  type FactCategory,
  type FactItem,
  type FactItems,
  type FactSource,
  type ImportCsvResult,
  type Verdict,
} from "@/lib/api"

const CSV_TEMPLATE =
  "source_id,category,title,claim_summary,fact_explanation,verdict,source_url\n" +
  '1,HEALTH_HOAX,"Contoh judul klaim","Ringkasan klaim","Penjelasan fakta",HOAX,https://contoh.go.id/hoax/1\n'

const PAGE_SIZE_OPTIONS = [10, 25, 50] as const
const DEFAULT_PAGE_SIZE = 25

const CATEGORIES: FactCategory[] = ["HEALTH_HOAX", "FINANCIAL_FRAUD", "GENERAL_NEWS", "PHISHING_LINK", "FILE_APK"]
const CATEGORY_LABELS: Record<FactCategory, string> = {
  HEALTH_HOAX: "Hoax kesehatan",
  FINANCIAL_FRAUD: "Penipuan finansial",
  GENERAL_NEWS: "Berita umum",
  PHISHING_LINK: "Tautan phishing",
  FILE_APK: "File APK",
}
const VERDICTS: Verdict[] = ["HOAX", "FACT", "MISLEADING", "UNVERIFIED"]

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

function verdictVariant(verdict: Verdict): BadgeVariant {
  if (verdict === "HOAX") return "high"
  if (verdict === "MISLEADING") return "medium"
  if (verdict === "FACT") return "low"
  return "unknown"
}

function syncBadge(item: FactItem): { label: string; variant: BadgeVariant } {
  if (item.sync_error) return { label: `Gagal: ${item.sync_error}`, variant: "high" }
  if (item.synced_at) return { label: `Tersinkron ${new Date(item.synced_at).toLocaleString("id-ID")}`, variant: "low" }
  return { label: "Belum disinkron", variant: "unknown" }
}

export function KnowledgeBaseList() {
  return (
    <React.Suspense fallback={<KnowledgeBaseListSkeleton />}>
      <KnowledgeBaseListInner />
    </React.Suspense>
  )
}

function KnowledgeBaseListSkeleton() {
  return (
    <Card>
      <CardHeader>
        <CardTitle>Knowledge Base</CardTitle>
        <CardDescription>Fact items yang bisa ditarik ML Service saat menjawab pesan pengguna.</CardDescription>
      </CardHeader>
      <CardContent className="flex flex-col gap-2">
        {Array.from({ length: 6 }).map((_, index) => (
          <Skeleton key={index} className="h-10 w-full" />
        ))}
      </CardContent>
    </Card>
  )
}

function KnowledgeBaseListInner() {
  const router = useRouter()
  const pathname = usePathname()
  const searchParams = useSearchParams()

  const page = parsePage(searchParams.get("page"))
  const pageSize = parsePageSize(searchParams.get("pageSize"))
  const category = searchParams.get("category") ?? ""
  const verdict = searchParams.get("verdict") ?? ""
  const isActive = searchParams.get("isActive") ?? ""
  const search = searchParams.get("search") ?? ""
  const offset = (page - 1) * pageSize

  const [data, setData] = React.useState<FactItems | null>(null)
  const [loading, setLoading] = React.useState(true)
  const [error, setError] = React.useState<string | null>(null)
  const [pendingId, setPendingId] = React.useState<string | null>(null)
  const [syncingAll, setSyncingAll] = React.useState(false)
  const [editing, setEditing] = React.useState<FactItem | "new" | null>(null)
  const [importing, setImporting] = React.useState(false)
  const [refreshKey, setRefreshKey] = React.useState(0)
  const [searchInput, setSearchInput] = React.useState(search)

  const hasFilters = Boolean(category || verdict || isActive || search)

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
        const result = await api.factItems(
          {
            limit: pageSize,
            offset,
            category: (category as FactCategory) || undefined,
            verdict: (verdict as Verdict) || undefined,
            isActive: isActive === "" ? undefined : isActive === "true",
            search: search || undefined,
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
  }, [offset, pageSize, category, verdict, isActive, search, refreshKey])

  async function syncOne(item: FactItem) {
    setPendingId(item.id)
    try {
      await api.syncFactItem(item.id)
      setRefreshKey((key) => key + 1)
    } catch {
      // Row stays as-is; the next successful action's refetch keeps state consistent.
    } finally {
      setPendingId(null)
    }
  }

  async function syncAll() {
    setSyncingAll(true)
    try {
      await api.syncAllFactItems()
      setRefreshKey((key) => key + 1)
    } catch {
      // Ditto.
    } finally {
      setSyncingAll(false)
    }
  }

  async function toggleActive(item: FactItem) {
    setPendingId(item.id)
    try {
      await api.actionOnFactItem(item.id, item.is_active ? "DEACTIVATE" : "ACTIVATE")
      setRefreshKey((key) => key + 1)
    } catch {
      // Ditto.
    } finally {
      setPendingId(null)
    }
  }

  const hasMore = data ? offset + data.items.length < data.total : false
  const totalPages = data && data.total > 0 ? Math.ceil(data.total / pageSize) : 1

  return (
    <div className="flex flex-col gap-6">
      <Card>
        <CardHeader className="flex flex-row items-start justify-between gap-4">
          <div>
            <CardTitle>Knowledge Base</CardTitle>
            <CardDescription>Fact items yang bisa ditarik ML Service saat menjawab pesan pengguna.</CardDescription>
          </div>
          <div className="flex gap-2">
            <Button variant="outline" size="sm" onClick={() => setImporting(true)}>
              Import CSV
            </Button>
            <Button variant="outline" size="sm" disabled={syncingAll} onClick={syncAll}>
              {syncingAll ? "Menyinkron…" : "Sync All"}
            </Button>
            <Button size="sm" onClick={() => setEditing("new")}>
              Buat Fact
            </Button>
          </div>
        </CardHeader>
        <CardContent className="flex flex-col gap-4">
          <div className="flex flex-wrap items-end gap-3">
            <div className="flex flex-col gap-1.5">
              <Label className="text-xs text-muted-foreground">Kategori</Label>
              <Select value={category || "all"} onValueChange={(v) => updateParams({ category: v === "all" ? null : v })}>
                <SelectTrigger size="sm" className="h-8 w-[170px]">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="all">Semua</SelectItem>
                  {CATEGORIES.map((value) => (
                    <SelectItem key={value} value={value}>
                      {CATEGORY_LABELS[value]}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
            <div className="flex flex-col gap-1.5">
              <Label className="text-xs text-muted-foreground">Verdict</Label>
              <Select value={verdict || "all"} onValueChange={(v) => updateParams({ verdict: v === "all" ? null : v })}>
                <SelectTrigger size="sm" className="h-8 w-[140px]">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="all">Semua</SelectItem>
                  {VERDICTS.map((value) => (
                    <SelectItem key={value} value={value}>
                      {value}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
            <div className="flex flex-col gap-1.5">
              <Label className="text-xs text-muted-foreground">Status</Label>
              <Select value={isActive || "all"} onValueChange={(v) => updateParams({ isActive: v === "all" ? null : v })}>
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
              <Label className="text-xs text-muted-foreground">Cari</Label>
              <Input
                className="h-8 w-[220px]"
                value={searchInput}
                onChange={(event) => setSearchInput(event.target.value)}
                onKeyDown={(event) => {
                  if (event.key === "Enter") updateParams({ search: searchInput || null })
                }}
                onBlur={() => updateParams({ search: searchInput || null })}
                placeholder="judul atau klaim…"
              />
            </div>
            {hasFilters ? (
              <Button
                variant="ghost"
                size="sm"
                onClick={() => {
                  setSearchInput("")
                  updateParams({ category: null, verdict: null, isActive: null, search: null })
                }}
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
              {hasFilters ? "Tidak ada fact item yang cocok dengan filter ini." : "Belum ada fact item."}
            </p>
          ) : (
            <div className="overflow-hidden rounded-lg border border-border">
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead>Judul</TableHead>
                    <TableHead>Kategori</TableHead>
                    <TableHead>Verdict</TableHead>
                    <TableHead>Sumber</TableHead>
                    <TableHead>Status sinkron</TableHead>
                    <TableHead className="w-64">
                      <span className="sr-only">Kelola</span>
                    </TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {data.items.map((item) => {
                    const isPending = pendingId === item.id
                    const badge = syncBadge(item)
                    return (
                      <TableRow key={item.id}>
                        <TableCell className="min-w-48 align-top text-sm font-medium">{item.title}</TableCell>
                        <TableCell className="align-top text-xs text-muted-foreground">
                          {CATEGORY_LABELS[item.category]}
                        </TableCell>
                        <TableCell className="align-top">
                          <Badge variant={verdictVariant(item.verdict)}>{item.verdict}</Badge>
                        </TableCell>
                        <TableCell className="align-top text-xs text-muted-foreground">
                          {item.source_name ?? "—"}
                        </TableCell>
                        <TableCell className="min-w-40 align-top text-xs">
                          <Badge variant={badge.variant}>{badge.label}</Badge>
                          {!item.is_active ? (
                            <div className="mt-1 text-xs text-muted-foreground">nonaktif</div>
                          ) : null}
                        </TableCell>
                        <TableCell className="align-top">
                          <div className="flex flex-wrap gap-1.5">
                            <Button variant="outline" size="sm" disabled={isPending} onClick={() => syncOne(item)}>
                              Sync
                            </Button>
                            <Button variant="outline" size="sm" disabled={isPending} onClick={() => setEditing(item)}>
                              Edit
                            </Button>
                            <Button variant="outline" size="sm" disabled={isPending} onClick={() => toggleActive(item)}>
                              {item.is_active ? "Nonaktifkan" : "Aktifkan"}
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

        <FactDialog
          target={editing}
          onClose={() => setEditing(null)}
          onDone={() => {
            setEditing(null)
            setRefreshKey((key) => key + 1)
          }}
        />
        <ImportCsvDialog
          open={importing}
          onClose={() => setImporting(false)}
          onImported={() => setRefreshKey((key) => key + 1)}
        />
      </Card>

      <SourcesPanel />
    </div>
  )
}

// --------------------------------------------------------------------------
// Create / edit dialog
// --------------------------------------------------------------------------

function FactDialog({
  target,
  onClose,
  onDone,
}: {
  target: FactItem | "new" | null
  onClose: () => void
  onDone: () => void
}) {
  return (
    <Dialog open={target !== null} onOpenChange={(open) => !open && onClose()}>
      <DialogContent className="sm:max-w-lg">
        {target ? (
          <FactForm key={target === "new" ? "new" : target.id} target={target} onClose={onClose} onDone={onDone} />
        ) : null}
      </DialogContent>
    </Dialog>
  )
}

function FactForm({
  target,
  onClose,
  onDone,
}: {
  target: FactItem | "new"
  onClose: () => void
  onDone: () => void
}) {
  const isNew = target === "new"
  const [sources, setSources] = React.useState<FactSource[]>([])
  const [sourceId, setSourceId] = React.useState(isNew ? "" : String(target.source_id))
  const [category, setCategory] = React.useState<FactCategory>(isNew ? "GENERAL_NEWS" : target.category)
  const [verdict, setVerdict] = React.useState<Verdict>(isNew ? "UNVERIFIED" : target.verdict)
  const [title, setTitle] = React.useState(isNew ? "" : target.title)
  const [claimSummary, setClaimSummary] = React.useState(isNew ? "" : target.claim_summary)
  const [factExplanation, setFactExplanation] = React.useState(isNew ? "" : target.fact_explanation)
  const [sourceUrl, setSourceUrl] = React.useState(isNew ? "" : target.source_url)
  const [submitting, setSubmitting] = React.useState(false)
  const [error, setError] = React.useState<string | null>(null)

  React.useEffect(() => {
    let cancelled = false
    api
      .factSources()
      .then((result) => {
        if (!cancelled && result.available) setSources(result.items)
      })
      .catch(() => {
        // Source select stays empty; the create button surfaces the real error on submit.
      })
    return () => {
      cancelled = true
    }
  }, [])

  async function submit() {
    if (!title.trim() || !claimSummary.trim() || !factExplanation.trim() || !sourceUrl.trim() || !sourceId) return
    setSubmitting(true)
    setError(null)
    try {
      if (isNew) {
        await api.createFactItem(
          Number(sourceId),
          category,
          title.trim(),
          claimSummary.trim(),
          factExplanation.trim(),
          verdict,
          sourceUrl.trim(),
        )
      } else {
        await api.actionOnFactItem(target.id, "UPDATE", {
          category,
          title: title.trim(),
          claim_summary: claimSummary.trim(),
          fact_explanation: factExplanation.trim(),
          verdict,
          source_url: sourceUrl.trim(),
        })
      }
      onDone()
    } catch (caught) {
      setError(caught instanceof GatewayError ? caught.message : "gagal menyimpan fact item")
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <>
      <DialogHeader>
        <DialogTitle>{isNew ? "Buat Fact Item" : "Edit Fact Item"}</DialogTitle>
        <DialogDescription>
          Mengubah fact item tidak melatih ulang model — hanya apa yang bisa ditarik ML Service yang berubah. Jangan
          lupa Sync setelah menyimpan.
        </DialogDescription>
      </DialogHeader>

      <div className="flex max-h-[60vh] flex-col gap-3 overflow-y-auto pr-1">
        <div className="grid grid-cols-2 gap-3">
          <div className="flex flex-col gap-1.5">
            <Label className="text-xs text-muted-foreground">Kategori</Label>
            <Select value={category} onValueChange={(v) => setCategory(v as FactCategory)}>
              <SelectTrigger className="h-9 w-full">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                {CATEGORIES.map((value) => (
                  <SelectItem key={value} value={value}>
                    {CATEGORY_LABELS[value]}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>
          <div className="flex flex-col gap-1.5">
            <Label className="text-xs text-muted-foreground">Verdict</Label>
            <Select value={verdict} onValueChange={(v) => setVerdict(v as Verdict)}>
              <SelectTrigger className="h-9 w-full">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                {VERDICTS.map((value) => (
                  <SelectItem key={value} value={value}>
                    {value}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>
        </div>

        <div className="flex flex-col gap-1.5">
          <Label className="text-xs text-muted-foreground">Sumber</Label>
          <Select value={sourceId} onValueChange={(v) => setSourceId(v ?? "")}>
            <SelectTrigger className="h-9 w-full">
              <SelectValue placeholder="Pilih sumber…" />
            </SelectTrigger>
            <SelectContent>
              {sources.map((source) => (
                <SelectItem key={source.id} value={String(source.id)}>
                  {source.name}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </div>

        <div className="flex flex-col gap-1.5">
          <Label className="text-xs text-muted-foreground">Judul</Label>
          <Input value={title} onChange={(event) => setTitle(event.target.value)} placeholder="mis. Modus arisan online bodong" />
        </div>

        <div className="flex flex-col gap-1.5">
          <Label className="text-xs text-muted-foreground">Ringkasan klaim</Label>
          <Textarea value={claimSummary} onChange={(event) => setClaimSummary(event.target.value)} rows={2} />
        </div>

        <div className="flex flex-col gap-1.5">
          <Label className="text-xs text-muted-foreground">Penjelasan fakta</Label>
          <Textarea value={factExplanation} onChange={(event) => setFactExplanation(event.target.value)} rows={3} />
        </div>

        <div className="flex flex-col gap-1.5">
          <Label className="text-xs text-muted-foreground">URL sumber</Label>
          <Input value={sourceUrl} onChange={(event) => setSourceUrl(event.target.value)} placeholder="https://…" />
        </div>

        {error ? <p className="text-sm text-destructive">{error}</p> : null}
      </div>

      <DialogFooter>
        <Button variant="outline" onClick={onClose} disabled={submitting}>
          Batal
        </Button>
        <Button
          onClick={submit}
          disabled={!title.trim() || !claimSummary.trim() || !factExplanation.trim() || !sourceUrl.trim() || !sourceId || submitting}
        >
          {submitting ? "Menyimpan…" : isNew ? "Buat" : "Simpan"}
        </Button>
      </DialogFooter>
    </>
  )
}

// --------------------------------------------------------------------------
// CSV bulk import — `source_id` must reference an existing Sumber Fakta row.
// --------------------------------------------------------------------------

function downloadCsvTemplate() {
  const blob = new Blob([CSV_TEMPLATE], { type: "text/csv;charset=utf-8" })
  const url = URL.createObjectURL(blob)
  const anchor = document.createElement("a")
  anchor.href = url
  anchor.download = "template-fact-items.csv"
  anchor.click()
  URL.revokeObjectURL(url)
}

function ImportCsvDialog({
  open,
  onClose,
  onImported,
}: {
  open: boolean
  onClose: () => void
  onImported: () => void
}) {
  return (
    <Dialog open={open} onOpenChange={(next) => !next && onClose()}>
      <DialogContent className="sm:max-w-lg">
        {open ? <ImportCsvForm onClose={onClose} onImported={onImported} /> : null}
      </DialogContent>
    </Dialog>
  )
}

function ImportCsvForm({ onClose, onImported }: { onClose: () => void; onImported: () => void }) {
  const [file, setFile] = React.useState<File | null>(null)
  const [submitting, setSubmitting] = React.useState(false)
  const [error, setError] = React.useState<string | null>(null)
  const [result, setResult] = React.useState<ImportCsvResult | null>(null)

  async function submit() {
    if (!file) return
    setSubmitting(true)
    setError(null)
    try {
      const outcome = await api.importFactItemsCsv(file)
      setResult(outcome)
      onImported()
    } catch (caught) {
      setError(caught instanceof GatewayError ? caught.message : "gagal mengimpor CSV")
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <>
      <DialogHeader>
        <DialogTitle>Import Fact Item dari CSV</DialogTitle>
        <DialogDescription>
          Setiap baris menjadi fact item baru (nonaktif dari Sync — pakai tombol Sync/Sync All setelahnya). Kolom{" "}
          <code>source_id</code> harus merujuk sumber yang sudah ada di panel Sumber Fakta di bawah.
        </DialogDescription>
      </DialogHeader>

      <div className="flex flex-col gap-3">
        <Button variant="ghost" size="sm" className="w-fit" onClick={downloadCsvTemplate}>
          Unduh template CSV
        </Button>

        <div className="flex flex-col gap-1.5">
          <Label className="text-xs text-muted-foreground">File CSV (maks. 2MB, 500 baris)</Label>
          <Input
            type="file"
            accept=".csv,text/csv"
            onChange={(event) => {
              setFile(event.target.files?.[0] ?? null)
              setResult(null)
            }}
          />
        </div>

        {error ? <p className="text-sm text-destructive">{error}</p> : null}

        {result ? (
          <div className="flex flex-col gap-2 rounded-lg border border-border p-3 text-sm">
            <p>
              Total {result.total} baris — <span className="font-medium text-risk-low">{result.created} dibuat</span>,{" "}
              <span className="font-medium text-destructive">{result.failed} gagal</span>.
            </p>
            {result.errors.length > 0 ? (
              <ul className="flex flex-col gap-1 text-xs text-muted-foreground">
                {result.errors.map((item) => (
                  <li key={item.row}>
                    Baris {item.row}: {item.reason}
                  </li>
                ))}
              </ul>
            ) : null}
          </div>
        ) : null}
      </div>

      <DialogFooter>
        <Button variant="outline" onClick={onClose}>
          {result ? "Tutup" : "Batal"}
        </Button>
        {!result ? (
          <Button onClick={submit} disabled={!file || submitting}>
            {submitting ? "Mengimpor…" : "Import"}
          </Button>
        ) : null}
      </DialogFooter>
    </>
  )
}

// --------------------------------------------------------------------------
// Sources panel — minimal list + create, so the fact form has a directory.
// --------------------------------------------------------------------------

function SourcesPanel() {
  const [sources, setSources] = React.useState<FactSource[]>([])
  const [loading, setLoading] = React.useState(true)
  const [available, setAvailable] = React.useState(true)
  const [name, setName] = React.useState("")
  const [baseUrl, setBaseUrl] = React.useState("")
  const [submitting, setSubmitting] = React.useState(false)
  const [error, setError] = React.useState<string | null>(null)
  const [refreshKey, setRefreshKey] = React.useState(0)

  React.useEffect(() => {
    let cancelled = false

    async function load() {
      setLoading(true)
      try {
        const result = await api.factSources()
        if (cancelled) return
        setAvailable(result.available)
        setSources(result.items)
      } catch {
        if (!cancelled) setAvailable(false)
      } finally {
        if (!cancelled) setLoading(false)
      }
    }

    void load()

    return () => {
      cancelled = true
    }
  }, [refreshKey])

  async function submit() {
    if (!name.trim() || !baseUrl.trim()) return
    setSubmitting(true)
    setError(null)
    try {
      await api.createFactSource(name.trim(), baseUrl.trim(), true)
      setName("")
      setBaseUrl("")
      setRefreshKey((key) => key + 1)
    } catch (caught) {
      setError(caught instanceof GatewayError ? caught.message : "gagal menyimpan sumber")
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <Card>
      <CardHeader>
        <CardTitle>Sumber Fakta</CardTitle>
        <CardDescription>Direktori sumber yang dirujuk fact item — dipakai saat membuat fact baru.</CardDescription>
      </CardHeader>
      <CardContent className="flex flex-col gap-4">
        {loading ? (
          <Skeleton className="h-8 w-full" />
        ) : !available ? (
          <p className="text-sm text-muted-foreground">Belum tersedia.</p>
        ) : sources.length === 0 ? (
          <p className="text-sm text-muted-foreground">Belum ada sumber.</p>
        ) : (
          <div className="overflow-hidden rounded-lg border border-border">
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>Nama</TableHead>
                  <TableHead>URL</TableHead>
                  <TableHead>Terpercaya</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {sources.map((source) => (
                  <TableRow key={source.id}>
                    <TableCell className="text-sm font-medium">{source.name}</TableCell>
                    <TableCell className="text-xs text-muted-foreground">{source.base_url}</TableCell>
                    <TableCell>
                      <Badge variant={source.is_trusted ? "low" : "unknown"}>
                        {source.is_trusted ? "Ya" : "Tidak"}
                      </Badge>
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </div>
        )}

        <div className="flex flex-wrap items-end gap-3 border-t border-border pt-4">
          <div className="flex flex-col gap-1.5">
            <Label className="text-xs text-muted-foreground">Nama sumber baru</Label>
            <Input className="h-8 w-[200px]" value={name} onChange={(event) => setName(event.target.value)} />
          </div>
          <div className="flex flex-col gap-1.5">
            <Label className="text-xs text-muted-foreground">Base URL</Label>
            <Input
              className="h-8 w-[240px]"
              value={baseUrl}
              onChange={(event) => setBaseUrl(event.target.value)}
              placeholder="https://…"
            />
          </div>
          <Button size="sm" disabled={!name.trim() || !baseUrl.trim() || submitting} onClick={submit}>
            {submitting ? "Menyimpan…" : "Tambah sumber"}
          </Button>
        </div>
        {error ? <p className="text-sm text-destructive">{error}</p> : null}
      </CardContent>
    </Card>
  )
}
