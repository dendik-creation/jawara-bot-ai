"use client"

import * as React from "react"

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
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select"
import { Skeleton } from "@/components/ui/skeleton"
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table"
import { Textarea } from "@/components/ui/textarea"
import {
  api,
  GatewayError,
  type DatasetDetail,
  type DatasetSource,
  type DatasetStatus,
  type Datasets,
} from "@/lib/api"

const SOURCES: DatasetSource[] = ["CURATED", "OPERATOR_FEEDBACK", "IMPORTED", "APPROVED_INTERNAL"]
const STATUSES: DatasetStatus[] = ["DRAFT", "VALIDATING", "VALIDATED", "REJECTED", "ARCHIVED"]

type BadgeVariant = "default" | "outline" | "high" | "medium" | "low" | "unknown"

function statusVariant(status: DatasetStatus): BadgeVariant {
  if (status === "VALIDATED") return "low"
  if (status === "DRAFT") return "medium"
  if (status === "REJECTED") return "high"
  if (status === "ARCHIVED") return "outline"
  return "unknown"
}

export function DatasetList({ refreshKey }: { refreshKey: number }) {
  const [status, setStatus] = React.useState<DatasetStatus | "">("")
  const [data, setData] = React.useState<Datasets | null>(null)
  const [loading, setLoading] = React.useState(true)
  const [error, setError] = React.useState<string | null>(null)
  const [creating, setCreating] = React.useState(false)
  const [viewing, setViewing] = React.useState<string | null>(null)
  const [localRefresh, setLocalRefresh] = React.useState(0)

  React.useEffect(() => {
    let cancelled = false
    const controller = new AbortController()

    async function load() {
      setLoading(true)
      setError(null)
      try {
        const result = await api.datasets({ status: status || undefined }, controller.signal)
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
  }, [status, refreshKey, localRefresh])

  function refetch() {
    setLocalRefresh((key) => key + 1)
  }

  return (
    <Card>
      <CardHeader className="flex flex-row items-start justify-between gap-4">
        <div>
          <CardTitle>Datasets</CardTitle>
          <CardDescription>Data latih terkurasi, versioned, dan tervalidasi — input untuk Training Jobs.</CardDescription>
        </div>
        <Button size="sm" onClick={() => setCreating(true)}>
          Buat Dataset
        </Button>
      </CardHeader>
      <CardContent className="flex flex-col gap-4">
        <div className="flex flex-wrap items-end gap-3">
          <div className="flex flex-col gap-1.5">
            <Label className="text-xs text-muted-foreground">Status</Label>
            <Select value={status || "all"} onValueChange={(v) => setStatus(v === "all" ? "" : (v as DatasetStatus))}>
              <SelectTrigger size="sm" className="h-8 w-[150px]">
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
        </div>

        {error ? (
          <p className="text-sm text-muted-foreground">{error}</p>
        ) : loading && !data ? (
          <div className="flex flex-col gap-2">
            {Array.from({ length: 3 }).map((_, index) => (
              <Skeleton key={index} className="h-10 w-full" />
            ))}
          </div>
        ) : !data?.available ? (
          <p className="text-sm text-muted-foreground">Belum tersedia ({data?.reason ?? "tidak diketahui"}).</p>
        ) : data.items.length === 0 ? (
          <p className="text-sm text-muted-foreground">Belum ada dataset.</p>
        ) : (
          <div className="overflow-hidden rounded-lg border border-border">
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>Nama</TableHead>
                  <TableHead>Versi</TableHead>
                  <TableHead>Sumber</TableHead>
                  <TableHead>Sample</TableHead>
                  <TableHead>Status</TableHead>
                  <TableHead className="w-32">
                    <span className="sr-only">Kelola</span>
                  </TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {data.items.map((item) => (
                  <TableRow key={item.id}>
                    <TableCell className="text-sm font-medium">{item.name}</TableCell>
                    <TableCell className="text-xs text-muted-foreground">v{item.version}</TableCell>
                    <TableCell className="text-xs text-muted-foreground">{item.source}</TableCell>
                    <TableCell className="text-xs text-muted-foreground">{item.sample_count}</TableCell>
                    <TableCell>
                      <Badge variant={statusVariant(item.status)}>{item.status}</Badge>
                    </TableCell>
                    <TableCell>
                      <Button variant="outline" size="sm" onClick={() => setViewing(item.id)}>
                        Buka
                      </Button>
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </div>
        )}
      </CardContent>

      <CreateDatasetDialog
        open={creating}
        onClose={() => setCreating(false)}
        onDone={() => {
          setCreating(false)
          refetch()
        }}
      />
      <DatasetDetailDialog
        datasetId={viewing}
        onClose={() => setViewing(null)}
        onChanged={refetch}
      />
    </Card>
  )
}

function CreateDatasetDialog({ open, onClose, onDone }: { open: boolean; onClose: () => void; onDone: () => void }) {
  return (
    <Dialog open={open} onOpenChange={(next) => !next && onClose()}>
      <DialogContent className="sm:max-w-lg">{open ? <CreateDatasetForm onClose={onClose} onDone={onDone} /> : null}</DialogContent>
    </Dialog>
  )
}

function CreateDatasetForm({ onClose, onDone }: { onClose: () => void; onDone: () => void }) {
  const [name, setName] = React.useState("")
  const [version, setVersion] = React.useState("1")
  const [source, setSource] = React.useState<DatasetSource>("CURATED")
  const [description, setDescription] = React.useState("")
  const [submitting, setSubmitting] = React.useState(false)
  const [error, setError] = React.useState<string | null>(null)

  async function submit() {
    if (!name.trim()) return
    setSubmitting(true)
    setError(null)
    try {
      await api.createDataset(name.trim(), Number(version) || 1, source, description.trim() || undefined)
      onDone()
    } catch (caught) {
      setError(caught instanceof GatewayError ? caught.message : "gagal membuat dataset")
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <>
      <DialogHeader>
        <DialogTitle>Buat Dataset</DialogTitle>
        <DialogDescription>Dataset baru selalu mulai sebagai DRAFT — tambahkan sample lalu validasi.</DialogDescription>
      </DialogHeader>

      <div className="flex flex-col gap-3">
        <div className="flex flex-col gap-1.5">
          <Label className="text-xs text-muted-foreground">Nama</Label>
          <Input value={name} onChange={(event) => setName(event.target.value)} placeholder="mis. health-hoax" />
        </div>
        <div className="grid grid-cols-2 gap-3">
          <div className="flex flex-col gap-1.5">
            <Label className="text-xs text-muted-foreground">Versi</Label>
            <Input type="number" min={1} value={version} onChange={(event) => setVersion(event.target.value)} />
          </div>
          <div className="flex flex-col gap-1.5">
            <Label className="text-xs text-muted-foreground">Sumber</Label>
            <Select value={source} onValueChange={(v) => setSource(v as DatasetSource)}>
              <SelectTrigger className="h-9 w-full">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                {SOURCES.map((value) => (
                  <SelectItem key={value} value={value}>
                    {value}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>
        </div>
        <div className="flex flex-col gap-1.5">
          <Label className="text-xs text-muted-foreground">Deskripsi</Label>
          <Textarea value={description} onChange={(event) => setDescription(event.target.value)} rows={2} />
        </div>
        {error ? <p className="text-sm text-destructive">{error}</p> : null}
      </div>

      <DialogFooter>
        <Button variant="outline" onClick={onClose} disabled={submitting}>
          Batal
        </Button>
        <Button onClick={submit} disabled={!name.trim() || submitting}>
          {submitting ? "Membuat…" : "Buat"}
        </Button>
      </DialogFooter>
    </>
  )
}

function DatasetDetailDialog({
  datasetId,
  onClose,
  onChanged,
}: {
  datasetId: string | null
  onClose: () => void
  onChanged: () => void
}) {
  return (
    <Dialog open={datasetId !== null} onOpenChange={(open) => !open && onClose()}>
      <DialogContent className="sm:max-w-2xl">
        {datasetId ? (
          <DatasetDetailView key={datasetId} datasetId={datasetId} onClose={onClose} onChanged={onChanged} />
        ) : null}
      </DialogContent>
    </Dialog>
  )
}

function DatasetDetailView({
  datasetId,
  onClose,
  onChanged,
}: {
  datasetId: string
  onClose: () => void
  onChanged: () => void
}) {
  const [dataset, setDataset] = React.useState<DatasetDetail | null>(null)
  const [loading, setLoading] = React.useState(true)
  const [error, setError] = React.useState<string | null>(null)
  const [busy, setBusy] = React.useState(false)
  const [newText, setNewText] = React.useState("")
  const [newLabel, setNewLabel] = React.useState("")
  const [refresh, setRefresh] = React.useState(0)

  React.useEffect(() => {
    let cancelled = false

    async function load() {
      setLoading(true)
      setError(null)
      try {
        const result = await api.dataset(datasetId)
        if (!cancelled) setDataset(result)
      } catch (caught) {
        if (!cancelled) setError(caught instanceof GatewayError ? caught.message : "gagal memuat dataset")
      } finally {
        if (!cancelled) setLoading(false)
      }
    }

    void load()
    return () => {
      cancelled = true
    }
  }, [datasetId, refresh])

  function refetch() {
    setRefresh((key) => key + 1)
    onChanged()
  }

  async function runAction(action: "VALIDATE" | "ARCHIVE") {
    setBusy(true)
    try {
      await api.actionOnDataset(datasetId, action)
      refetch()
    } catch (caught) {
      setError(caught instanceof GatewayError ? caught.message : "aksi gagal")
    } finally {
      setBusy(false)
    }
  }

  async function addSample() {
    if (!newText.trim() || !newLabel.trim()) return
    setBusy(true)
    try {
      await api.addDatasetSample(datasetId, newText.trim(), newLabel.trim())
      setNewText("")
      setNewLabel("")
      refetch()
    } catch (caught) {
      setError(caught instanceof GatewayError ? caught.message : "gagal menambah sample")
    } finally {
      setBusy(false)
    }
  }

  async function removeSample(sampleId: string) {
    setBusy(true)
    try {
      await api.removeDatasetSample(datasetId, sampleId)
      refetch()
    } catch (caught) {
      setError(caught instanceof GatewayError ? caught.message : "gagal menghapus sample")
    } finally {
      setBusy(false)
    }
  }

  if (loading || !dataset) {
    return (
      <div className="flex flex-col gap-2">
        {Array.from({ length: 4 }).map((_, index) => (
          <Skeleton key={index} className="h-8 w-full" />
        ))}
      </div>
    )
  }

  const isDraft = dataset.status === "DRAFT"

  return (
    <>
      <DialogHeader>
        <DialogTitle className="flex items-center gap-2">
          {dataset.name} v{dataset.version}
          <Badge variant={statusVariant(dataset.status)}>{dataset.status}</Badge>
        </DialogTitle>
        <DialogDescription>
          {dataset.description ?? "Tanpa deskripsi."}
          {dataset.validation_notes ? ` — Catatan validasi: ${dataset.validation_notes}` : ""}
        </DialogDescription>
      </DialogHeader>

      <div className="flex flex-col gap-3 max-h-[55vh] overflow-y-auto pr-1">
        <div className="flex flex-wrap gap-1.5 text-xs">
          {Object.entries(dataset.label_counts).map(([label, count]) => (
            <Badge key={label} variant="outline">
              {label}: {count}
            </Badge>
          ))}
        </div>

        {dataset.samples.length === 0 ? (
          <p className="text-sm text-muted-foreground">Belum ada sample.</p>
        ) : (
          <div className="overflow-hidden rounded-lg border border-border">
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>Teks</TableHead>
                  <TableHead>Label</TableHead>
                  {isDraft ? (
                    <TableHead className="w-20">
                      <span className="sr-only">Hapus</span>
                    </TableHead>
                  ) : null}
                </TableRow>
              </TableHeader>
              <TableBody>
                {dataset.samples.map((sample) => (
                  <TableRow key={sample.id}>
                    <TableCell className="max-w-72 truncate text-xs">{sample.text}</TableCell>
                    <TableCell className="text-xs text-muted-foreground">{sample.label}</TableCell>
                    {isDraft ? (
                      <TableCell>
                        <Button variant="ghost" size="sm" disabled={busy} onClick={() => removeSample(sample.id)}>
                          Hapus
                        </Button>
                      </TableCell>
                    ) : null}
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </div>
        )}

        {isDraft ? (
          <div className="flex flex-col gap-2 rounded-lg border border-border p-3">
            <Label className="text-xs text-muted-foreground">Tambah sample manual</Label>
            <Textarea value={newText} onChange={(event) => setNewText(event.target.value)} rows={2} placeholder="Teks sample" />
            <Input value={newLabel} onChange={(event) => setNewLabel(event.target.value)} placeholder="Label (mis. HEALTH_HOAX atau NOT_A_THREAT)" />
            <Button size="sm" className="w-fit" disabled={!newText.trim() || !newLabel.trim() || busy} onClick={addSample}>
              Tambah sample
            </Button>
          </div>
        ) : null}

        {error ? <p className="text-sm text-destructive">{error}</p> : null}
      </div>

      <DialogFooter>
        <Button variant="outline" onClick={onClose}>
          Tutup
        </Button>
        {isDraft ? (
          <Button disabled={busy} onClick={() => runAction("VALIDATE")}>
            Validasi
          </Button>
        ) : null}
        {dataset.status !== "ARCHIVED" ? (
          <Button variant="outline" disabled={busy} onClick={() => runAction("ARCHIVE")}>
            Archive
          </Button>
        ) : null}
      </DialogFooter>
    </>
  )
}
