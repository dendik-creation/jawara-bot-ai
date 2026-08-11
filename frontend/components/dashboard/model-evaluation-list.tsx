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
import { Label } from "@/components/ui/label"
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select"
import { Skeleton } from "@/components/ui/skeleton"
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table"
import {
  api,
  GatewayError,
  type DatasetItem,
  type ModelEvaluationItem,
  type ModelEvaluationStatus,
  type ModelEvaluations,
  type TrainingJobItem,
} from "@/lib/api"

const STATUSES: ModelEvaluationStatus[] = ["QUEUED", "RUNNING", "COMPLETED", "FAILED", "CANCELLED"]
const CANCELLABLE = new Set<ModelEvaluationStatus>(["QUEUED", "RUNNING"])

type BadgeVariant = "default" | "outline" | "high" | "medium" | "low" | "unknown"

function statusVariant(status: ModelEvaluationStatus): BadgeVariant {
  if (status === "COMPLETED") return "low"
  if (status === "FAILED") return "high"
  if (status === "CANCELLED") return "outline"
  if (status === "RUNNING") return "medium"
  return "unknown"
}

export function ModelEvaluationList() {
  const [status, setStatus] = React.useState<ModelEvaluationStatus | "">("")
  const [data, setData] = React.useState<ModelEvaluations | null>(null)
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
        const result = await api.modelEvaluations({ status: status || undefined }, controller.signal)
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
          <CardTitle>Evaluation</CardTitle>
          <CardDescription>
            Gerbang antara model selesai dilatih dan model boleh melayani produksi — dievaluasi terhadap dataset uji tetap.
          </CardDescription>
        </div>
        <Button size="sm" onClick={() => setCreating(true)}>
          Buat Evaluasi
        </Button>
      </CardHeader>
      <CardContent className="flex flex-col gap-4">
        <div className="flex flex-wrap items-end gap-3">
          <div className="flex flex-col gap-1.5">
            <Label className="text-xs text-muted-foreground">Status</Label>
            <Select
              value={status || "all"}
              onValueChange={(v) => setStatus(v === "all" ? "" : (v as ModelEvaluationStatus))}
            >
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
          <p className="text-sm text-muted-foreground">Belum ada evaluasi.</p>
        ) : (
          <div className="overflow-hidden rounded-lg border border-border">
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>Model</TableHead>
                  <TableHead>Dataset uji</TableHead>
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
                      {item.generated_model_version ?? item.training_job_base_model}
                    </TableCell>
                    <TableCell className="text-xs text-muted-foreground">
                      {item.dataset_name} v{item.dataset_version}
                    </TableCell>
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

      <CreateEvaluationDialog
        open={creating}
        onClose={() => setCreating(false)}
        onDone={() => {
          setCreating(false)
          refetch()
        }}
      />
      <EvaluationDetailDialog evaluationId={viewing} onClose={() => setViewing(null)} onChanged={refetch} />
    </Card>
  )
}

function CreateEvaluationDialog({
  open,
  onClose,
  onDone,
}: {
  open: boolean
  onClose: () => void
  onDone: () => void
}) {
  return (
    <Dialog open={open} onOpenChange={(next) => !next && onClose()}>
      <DialogContent className="sm:max-w-lg">
        {open ? <CreateEvaluationForm onClose={onClose} onDone={onDone} /> : null}
      </DialogContent>
    </Dialog>
  )
}

function CreateEvaluationForm({ onClose, onDone }: { onClose: () => void; onDone: () => void }) {
  const [jobs, setJobs] = React.useState<TrainingJobItem[]>([])
  const [datasets, setDatasets] = React.useState<DatasetItem[]>([])
  const [trainingJobId, setTrainingJobId] = React.useState("")
  const [datasetId, setDatasetId] = React.useState("")
  const [submitting, setSubmitting] = React.useState(false)
  const [error, setError] = React.useState<string | null>(null)

  React.useEffect(() => {
    let cancelled = false
    api
      .trainingJobs({ status: "COMPLETED", limit: 50 })
      .then((result) => {
        if (!cancelled && result.available) setJobs(result.items)
      })
      .catch(() => {
        // Training job select stays empty; submit surfaces the real error.
      })
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
    if (!trainingJobId || !datasetId) return
    setSubmitting(true)
    setError(null)
    try {
      await api.createModelEvaluation(trainingJobId, datasetId)
      onDone()
    } catch (caught) {
      setError(caught instanceof GatewayError ? caught.message : "gagal membuat evaluasi")
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <>
      <DialogHeader>
        <DialogTitle>Buat Evaluasi</DialogTitle>
        <DialogDescription>
          Hanya training job berstatus COMPLETED yang bisa dievaluasi, terhadap dataset uji berstatus VALIDATED.
        </DialogDescription>
      </DialogHeader>

      <div className="flex flex-col gap-3">
        <div className="flex flex-col gap-1.5">
          <Label className="text-xs text-muted-foreground">Training job (COMPLETED)</Label>
          <Select value={trainingJobId} onValueChange={(v) => setTrainingJobId(v ?? "")}>
            <SelectTrigger className="h-9 w-full">
              <SelectValue placeholder={jobs.length ? "Pilih training job…" : "Tidak ada training job COMPLETED"} />
            </SelectTrigger>
            <SelectContent>
              {jobs.map((job) => (
                <SelectItem key={job.id} value={job.id}>
                  {job.generated_model_version ?? job.base_model} ({job.dataset_name} v{job.dataset_version})
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </div>

        <div className="flex flex-col gap-1.5">
          <Label className="text-xs text-muted-foreground">Dataset uji (VALIDATED)</Label>
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

        {error ? <p className="text-sm text-destructive">{error}</p> : null}
      </div>

      <DialogFooter>
        <Button variant="outline" onClick={onClose} disabled={submitting}>
          Batal
        </Button>
        <Button onClick={submit} disabled={!trainingJobId || !datasetId || submitting}>
          {submitting ? "Membuat…" : "Buat"}
        </Button>
      </DialogFooter>
    </>
  )
}

function EvaluationDetailDialog({
  evaluationId,
  onClose,
  onChanged,
}: {
  evaluationId: string | null
  onClose: () => void
  onChanged: () => void
}) {
  return (
    <Dialog open={evaluationId !== null} onOpenChange={(open) => !open && onClose()}>
      <DialogContent className="sm:max-w-lg">
        {evaluationId ? (
          <EvaluationDetailView key={evaluationId} evaluationId={evaluationId} onClose={onClose} onChanged={onChanged} />
        ) : null}
      </DialogContent>
    </Dialog>
  )
}

function EvaluationDetailView({
  evaluationId,
  onClose,
  onChanged,
}: {
  evaluationId: string
  onClose: () => void
  onChanged: () => void
}) {
  const [evaluation, setEvaluation] = React.useState<ModelEvaluationItem | null>(null)
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
        const result = await api.modelEvaluation(evaluationId)
        if (!cancelled) setEvaluation(result)
      } catch (caught) {
        if (!cancelled) setError(caught instanceof GatewayError ? caught.message : "gagal memuat evaluasi")
      } finally {
        if (!cancelled) setLoading(false)
      }
    }

    void load()
    return () => {
      cancelled = true
    }
  }, [evaluationId, refresh])

  async function cancelEvaluation() {
    setBusy(true)
    try {
      await api.actionOnModelEvaluation(evaluationId, "CANCEL")
      setRefresh((key) => key + 1)
      onChanged()
    } catch (caught) {
      setError(caught instanceof GatewayError ? caught.message : "gagal membatalkan evaluasi")
    } finally {
      setBusy(false)
    }
  }

  if (loading || !evaluation) {
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
          {evaluation.generated_model_version ?? evaluation.training_job_base_model}
          <Badge variant={statusVariant(evaluation.status)}>{evaluation.status}</Badge>
        </DialogTitle>
        <DialogDescription>
          Dataset uji: {evaluation.dataset_name} v{evaluation.dataset_version}
        </DialogDescription>
      </DialogHeader>

      <div className="flex flex-col gap-2 text-sm">
        <Row label="Base model" value={evaluation.training_job_base_model} />
        <Row label="Progress" value={evaluation.progress ?? "—"} />
        <Row label="Mulai" value={evaluation.started_at ? new Date(evaluation.started_at).toLocaleString("id-ID") : "—"} />
        <Row
          label="Selesai"
          value={evaluation.finished_at ? new Date(evaluation.finished_at).toLocaleString("id-ID") : "—"}
        />
        {evaluation.metrics ? <Row label="Metrics" value={JSON.stringify(evaluation.metrics)} /> : null}
        {evaluation.error_message ? (
          <p className="rounded-lg border border-destructive/40 bg-destructive/5 p-2 text-xs text-destructive">
            {evaluation.error_message}
          </p>
        ) : null}
        {error ? <p className="text-sm text-destructive">{error}</p> : null}
      </div>

      <DialogFooter>
        <Button variant="outline" onClick={onClose}>
          Tutup
        </Button>
        {CANCELLABLE.has(evaluation.status) ? (
          <Button variant="outline" disabled={busy} onClick={cancelEvaluation}>
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
