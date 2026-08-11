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
import { api, GatewayError, type DatasetItem, type TrainingJobItem, type TrainingJobStatus, type TrainingJobs } from "@/lib/api"

const STATUSES: TrainingJobStatus[] = ["QUEUED", "RUNNING", "EVALUATING", "COMPLETED", "FAILED", "CANCELLED"]
const CANCELLABLE = new Set<TrainingJobStatus>(["QUEUED", "RUNNING"])

type BadgeVariant = "default" | "outline" | "high" | "medium" | "low" | "unknown"

function statusVariant(status: TrainingJobStatus): BadgeVariant {
  if (status === "COMPLETED") return "low"
  if (status === "FAILED") return "high"
  if (status === "CANCELLED") return "outline"
  if (status === "RUNNING" || status === "EVALUATING") return "medium"
  return "unknown"
}

export function TrainingJobList() {
  const [status, setStatus] = React.useState<TrainingJobStatus | "">("")
  const [data, setData] = React.useState<TrainingJobs | null>(null)
  const [loading, setLoading] = React.useState(true)
  const [error, setError] = React.useState<string | null>(null)
  const [creating, setCreating] = React.useState(false)
  const [viewing, setViewing] = React.useState<string | null>(null)
  const [refreshKey, setRefreshKey] = React.useState(0)

  React.useEffect(() => {
    let cancelled = false
    const controller = new AbortController()

    async function load() {
      setLoading(true)
      setError(null)
      try {
        const result = await api.trainingJobs({ status: status || undefined }, controller.signal)
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
  }, [status, refreshKey])

  function refetch() {
    setRefreshKey((key) => key + 1)
  }

  return (
    <Card>
      <CardHeader className="flex flex-row items-start justify-between gap-4">
        <div>
          <CardTitle>Training Jobs</CardTitle>
          <CardDescription>
            Operasi asinkron terkontrol — job hanya dibuat di sini, eksekusi berjalan di worker terpisah.
          </CardDescription>
        </div>
        <Button size="sm" onClick={() => setCreating(true)}>
          Buat Job
        </Button>
      </CardHeader>
      <CardContent className="flex flex-col gap-4">
        <div className="flex flex-wrap items-end gap-3">
          <div className="flex flex-col gap-1.5">
            <Label className="text-xs text-muted-foreground">Status</Label>
            <Select value={status || "all"} onValueChange={(v) => setStatus(v === "all" ? "" : (v as TrainingJobStatus))}>
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
          <p className="text-sm text-muted-foreground">Belum ada training job.</p>
        ) : (
          <div className="overflow-hidden rounded-lg border border-border">
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>Dataset</TableHead>
                  <TableHead>Base model</TableHead>
                  <TableHead>Status</TableHead>
                  <TableHead>Dibuat</TableHead>
                  <TableHead className="w-24">
                    <span className="sr-only">Kelola</span>
                  </TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {data.items.map((item) => (
                  <TableRow key={item.id}>
                    <TableCell className="text-sm font-medium">
                      {item.dataset_name} v{item.dataset_version}
                    </TableCell>
                    <TableCell className="text-xs text-muted-foreground">{item.base_model}</TableCell>
                    <TableCell>
                      <Badge variant={statusVariant(item.status)}>{item.status}</Badge>
                    </TableCell>
                    <TableCell className="text-xs text-muted-foreground">
                      {new Date(item.created_at).toLocaleString("id-ID")}
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

      <CreateJobDialog
        open={creating}
        onClose={() => setCreating(false)}
        onDone={() => {
          setCreating(false)
          refetch()
        }}
      />
      <JobDetailDialog jobId={viewing} onClose={() => setViewing(null)} onChanged={refetch} />
    </Card>
  )
}

function CreateJobDialog({ open, onClose, onDone }: { open: boolean; onClose: () => void; onDone: () => void }) {
  return (
    <Dialog open={open} onOpenChange={(next) => !next && onClose()}>
      <DialogContent className="sm:max-w-lg">{open ? <CreateJobForm onClose={onClose} onDone={onDone} /> : null}</DialogContent>
    </Dialog>
  )
}

function CreateJobForm({ onClose, onDone }: { onClose: () => void; onDone: () => void }) {
  const [datasets, setDatasets] = React.useState<DatasetItem[]>([])
  const [datasetId, setDatasetId] = React.useState("")
  const [baseModel, setBaseModel] = React.useState("")
  const [epochs, setEpochs] = React.useState("")
  const [learningRate, setLearningRate] = React.useState("")
  const [batchSize, setBatchSize] = React.useState("")
  const [validationSplit, setValidationSplit] = React.useState("")
  const [submitting, setSubmitting] = React.useState(false)
  const [error, setError] = React.useState<string | null>(null)

  React.useEffect(() => {
    let cancelled = false
    api
      .datasets({ status: "VALIDATED", limit: 50 })
      .then((result) => {
        if (!cancelled && result.available) setDatasets(result.items)
      })
      .catch(() => {
        // Dataset select stays empty; submit surfaces the real error.
      })
    return () => {
      cancelled = true
    }
  }, [])

  async function submit() {
    if (!datasetId || !baseModel.trim()) return
    setSubmitting(true)
    setError(null)
    try {
      await api.createTrainingJob(datasetId, baseModel.trim(), {
        epochs: epochs ? Number(epochs) : undefined,
        learningRate: learningRate ? Number(learningRate) : undefined,
        batchSize: batchSize ? Number(batchSize) : undefined,
        validationSplit: validationSplit ? Number(validationSplit) : undefined,
      })
      onDone()
    } catch (caught) {
      setError(caught instanceof GatewayError ? caught.message : "gagal membuat training job")
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <>
      <DialogHeader>
        <DialogTitle>Buat Training Job</DialogTitle>
        <DialogDescription>
          Hanya dataset berstatus VALIDATED yang bisa dipakai. Job dijalankan asinkron di worker terpisah.
        </DialogDescription>
      </DialogHeader>

      <div className="flex flex-col gap-3">
        <div className="flex flex-col gap-1.5">
          <Label className="text-xs text-muted-foreground">Dataset (VALIDATED)</Label>
          <Select value={datasetId} onValueChange={(v) => setDatasetId(v ?? "")}>
            <SelectTrigger className="h-9 w-full">
              <SelectValue placeholder={datasets.length ? "Pilih dataset…" : "Tidak ada dataset VALIDATED"} />
            </SelectTrigger>
            <SelectContent>
              {datasets.map((dataset) => (
                <SelectItem key={dataset.id} value={dataset.id}>
                  {dataset.name} v{dataset.version} ({dataset.sample_count} sample)
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </div>

        <div className="flex flex-col gap-1.5">
          <Label className="text-xs text-muted-foreground">Base model</Label>
          <Input value={baseModel} onChange={(event) => setBaseModel(event.target.value)} placeholder="mis. hash-embed-v0" />
        </div>

        <div className="grid grid-cols-2 gap-3">
          <div className="flex flex-col gap-1.5">
            <Label className="text-xs text-muted-foreground">Epochs</Label>
            <Input type="number" value={epochs} onChange={(event) => setEpochs(event.target.value)} />
          </div>
          <div className="flex flex-col gap-1.5">
            <Label className="text-xs text-muted-foreground">Learning rate</Label>
            <Input type="number" step="0.0001" value={learningRate} onChange={(event) => setLearningRate(event.target.value)} />
          </div>
          <div className="flex flex-col gap-1.5">
            <Label className="text-xs text-muted-foreground">Batch size</Label>
            <Input type="number" value={batchSize} onChange={(event) => setBatchSize(event.target.value)} />
          </div>
          <div className="flex flex-col gap-1.5">
            <Label className="text-xs text-muted-foreground">Validation split</Label>
            <Input type="number" step="0.05" min={0} max={1} value={validationSplit} onChange={(event) => setValidationSplit(event.target.value)} />
          </div>
        </div>

        {error ? <p className="text-sm text-destructive">{error}</p> : null}
      </div>

      <DialogFooter>
        <Button variant="outline" onClick={onClose} disabled={submitting}>
          Batal
        </Button>
        <Button onClick={submit} disabled={!datasetId || !baseModel.trim() || submitting}>
          {submitting ? "Membuat…" : "Buat"}
        </Button>
      </DialogFooter>
    </>
  )
}

function JobDetailDialog({
  jobId,
  onClose,
  onChanged,
}: {
  jobId: string | null
  onClose: () => void
  onChanged: () => void
}) {
  return (
    <Dialog open={jobId !== null} onOpenChange={(open) => !open && onClose()}>
      <DialogContent className="sm:max-w-lg">
        {jobId ? <JobDetailView key={jobId} jobId={jobId} onClose={onClose} onChanged={onChanged} /> : null}
      </DialogContent>
    </Dialog>
  )
}

function JobDetailView({ jobId, onClose, onChanged }: { jobId: string; onClose: () => void; onChanged: () => void }) {
  const [job, setJob] = React.useState<TrainingJobItem | null>(null)
  const [loading, setLoading] = React.useState(true)
  const [error, setError] = React.useState<string | null>(null)
  const [busy, setBusy] = React.useState(false)
  const [refresh, setRefresh] = React.useState(0)

  React.useEffect(() => {
    let cancelled = false

    async function load() {
      setLoading(true)
      setError(null)
      try {
        const result = await api.trainingJob(jobId)
        if (!cancelled) setJob(result)
      } catch (caught) {
        if (!cancelled) setError(caught instanceof GatewayError ? caught.message : "gagal memuat job")
      } finally {
        if (!cancelled) setLoading(false)
      }
    }

    void load()
    return () => {
      cancelled = true
    }
  }, [jobId, refresh])

  async function cancelJob() {
    setBusy(true)
    try {
      await api.actionOnTrainingJob(jobId, "CANCEL")
      setRefresh((key) => key + 1)
      onChanged()
    } catch (caught) {
      setError(caught instanceof GatewayError ? caught.message : "gagal membatalkan job")
    } finally {
      setBusy(false)
    }
  }

  if (loading || !job) {
    return (
      <div className="flex flex-col gap-2">
        {Array.from({ length: 4 }).map((_, index) => (
          <Skeleton key={index} className="h-8 w-full" />
        ))}
      </div>
    )
  }

  return (
    <>
      <DialogHeader>
        <DialogTitle className="flex items-center gap-2">
          {job.dataset_name} v{job.dataset_version}
          <Badge variant={statusVariant(job.status)}>{job.status}</Badge>
        </DialogTitle>
        <DialogDescription>Base model: {job.base_model}</DialogDescription>
      </DialogHeader>

      <div className="flex flex-col gap-2 text-sm">
        <Row label="Epochs" value={job.epochs} />
        <Row label="Learning rate" value={job.learning_rate} />
        <Row label="Batch size" value={job.batch_size} />
        <Row label="Validation split" value={job.validation_split} />
        <Row label="Progress" value={job.progress ?? "—"} />
        <Row label="Mulai" value={job.started_at ? new Date(job.started_at).toLocaleString("id-ID") : "—"} />
        <Row label="Selesai" value={job.finished_at ? new Date(job.finished_at).toLocaleString("id-ID") : "—"} />
        <Row label="Model version" value={job.generated_model_version ?? "—"} />
        {job.metrics ? <Row label="Metrics" value={JSON.stringify(job.metrics)} /> : null}
        {job.error_message ? (
          <p className="rounded-lg border border-destructive/40 bg-destructive/5 p-2 text-xs text-destructive">
            {job.error_message}
          </p>
        ) : null}
        {error ? <p className="text-sm text-destructive">{error}</p> : null}
      </div>

      <DialogFooter>
        <Button variant="outline" onClick={onClose}>
          Tutup
        </Button>
        {CANCELLABLE.has(job.status) ? (
          <Button variant="outline" disabled={busy} onClick={cancelJob}>
            Cancel
          </Button>
        ) : null}
      </DialogFooter>
    </>
  )
}

function Row({ label, value }: { label: string; value: React.ReactNode }) {
  return (
    <div className="flex items-center justify-between">
      <span className="text-muted-foreground">{label}</span>
      <span className="font-medium">{value}</span>
    </div>
  )
}
