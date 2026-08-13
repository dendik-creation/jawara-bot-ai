"use client"

import * as React from "react"

import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Card, CardContent } from "@/components/ui/card"
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from "@/components/ui/dialog"
import { Label } from "@/components/ui/label"
import { MetricsSummary } from "@/components/dashboard/metrics-summary"
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select"
import { Skeleton } from "@/components/ui/skeleton"
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table"
import { toast } from "@/components/ui/toast"
import { api, GatewayError, type ModelVersionItem, type ModelVersionStatus, type ModelVersions } from "@/lib/api"

const STATUSES: ModelVersionStatus[] = ["CANDIDATE", "VALIDATED", "PRODUCTION", "ARCHIVED"]

type BadgeVariant = "default" | "outline" | "high" | "medium" | "low" | "unknown"

function statusVariant(status: ModelVersionStatus): BadgeVariant {
  if (status === "PRODUCTION") return "low"
  if (status === "VALIDATED") return "medium"
  if (status === "ARCHIVED") return "outline"
  return "unknown"
}

export function ModelVersionList() {
  const [status, setStatus] = React.useState<ModelVersionStatus | "">("")
  const [data, setData] = React.useState<ModelVersions | null>(null)
  const [loading, setLoading] = React.useState(true)
  const [error, setError] = React.useState<string | null>(null)
  const [viewing, setViewing] = React.useState<string | null>(null)
  const [refreshKey, setRefreshKey] = React.useState(0)

  React.useEffect(() => {
    let cancelled = false
    const controller = new AbortController()

    async function load() {
      setLoading(true)
      setError(null)
      try {
        const result = await api.modelVersions({ status: status || undefined }, controller.signal)
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

  const productionVersion = data?.available ? data.items.find((item) => item.status === "PRODUCTION") : undefined

  return (
    <Card>
      <CardContent className="flex flex-col gap-4">
        {productionVersion ? (
          <div className="rounded-lg border border-border bg-muted/40 p-3">
            <p className="text-xs text-muted-foreground">Model production saat ini</p>
            <p className="text-sm font-medium">
              {productionVersion.generated_model_version ?? productionVersion.training_job_base_model}
            </p>
          </div>
        ) : null}

        <div className="flex flex-wrap items-end gap-3">
          <div className="flex flex-col gap-1.5">
            <Label className="text-xs text-muted-foreground">Status</Label>
            <Select value={status || "all"} onValueChange={(v) => setStatus(v === "all" ? "" : (v as ModelVersionStatus))}>
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
          <p className="text-sm text-muted-foreground">
            Belum ada model version — akan otomatis muncul begitu evaluasi model selesai dijalankan.
          </p>
        ) : (
          <div className="overflow-hidden rounded-lg border border-border">
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>Model</TableHead>
                  <TableHead>Dataset latih</TableHead>
                  <TableHead>Dataset uji</TableHead>
                  <TableHead>Status</TableHead>
                  <TableHead>Diperbarui</TableHead>
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
                      {item.training_dataset_name} v{item.training_dataset_version}
                    </TableCell>
                    <TableCell className="text-xs text-muted-foreground">
                      {item.evaluation_dataset_name} v{item.evaluation_dataset_version}
                    </TableCell>
                    <TableCell>
                      <Badge variant={statusVariant(item.status)}>{item.status}</Badge>
                    </TableCell>
                    <TableCell className="text-xs text-muted-foreground">
                      {new Date(item.updated_at).toLocaleString("id-ID")}
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

      <ModelVersionDetailDialog modelVersionId={viewing} onClose={() => setViewing(null)} onChanged={refetch} />
    </Card>
  )
}

function ModelVersionDetailDialog({
  modelVersionId,
  onClose,
  onChanged,
}: {
  modelVersionId: string | null
  onClose: () => void
  onChanged: () => void
}) {
  return (
    <Dialog open={modelVersionId !== null} onOpenChange={(open) => !open && onClose()}>
      <DialogContent className="sm:max-w-lg">
        {modelVersionId ? (
          <ModelVersionDetailView key={modelVersionId} modelVersionId={modelVersionId} onClose={onClose} onChanged={onChanged} />
        ) : null}
      </DialogContent>
    </Dialog>
  )
}

function ModelVersionDetailView({
  modelVersionId,
  onClose,
  onChanged,
}: {
  modelVersionId: string
  onClose: () => void
  onChanged: () => void
}) {
  const [modelVersion, setModelVersion] = React.useState<ModelVersionItem | null>(null)
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
        const result = await api.modelVersion(modelVersionId)
        if (!cancelled) setModelVersion(result)
      } catch (caught) {
        if (!cancelled) setError(caught instanceof GatewayError ? caught.message : "gagal memuat model version")
      } finally {
        if (!cancelled) setLoading(false)
      }
    }

    void load()
    return () => {
      cancelled = true
    }
  }, [modelVersionId, refresh])

  async function runAction(action: "VALIDATE" | "PROMOTE" | "ARCHIVE") {
    setBusy(true)
    setError(null)
    try {
      await api.actionOnModelVersion(modelVersionId, action)
      setRefresh((key) => key + 1)
      onChanged()
      const label = action === "VALIDATE" ? "divalidasi" : action === "PROMOTE" ? "dipromosikan ke production" : "diarsipkan"
      toast.success(`Model version ${label}`)
    } catch (caught) {
      setError(caught instanceof GatewayError ? caught.message : "gagal menjalankan aksi")
    } finally {
      setBusy(false)
    }
  }

  if (loading || !modelVersion) {
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
          {modelVersion.generated_model_version ?? modelVersion.training_job_base_model}
          <Badge variant={statusVariant(modelVersion.status)}>{modelVersion.status}</Badge>
        </DialogTitle>
        <DialogDescription>Base model: {modelVersion.training_job_base_model}</DialogDescription>
      </DialogHeader>

      <div className="flex flex-col gap-2 text-sm">
        <Row
          label="Dataset latih"
          value={`${modelVersion.training_dataset_name} v${modelVersion.training_dataset_version}`}
        />
        <Row
          label="Dataset uji"
          value={`${modelVersion.evaluation_dataset_name} v${modelVersion.evaluation_dataset_version}`}
        />
        {modelVersion.evaluation_metrics ? <MetricsSummary metrics={modelVersion.evaluation_metrics} /> : null}
        <Row label="Diperbarui" value={new Date(modelVersion.updated_at).toLocaleString("id-ID")} />
        {error ? <p className="text-sm text-destructive">{error}</p> : null}
      </div>

      <DialogFooter>
        <Button variant="outline" onClick={onClose}>
          Tutup
        </Button>
        {modelVersion.status === "CANDIDATE" ? (
          <Button variant="outline" disabled={busy} onClick={() => runAction("VALIDATE")}>
            Validasi
          </Button>
        ) : null}
        {modelVersion.status === "VALIDATED" ? (
          <Button disabled={busy} onClick={() => runAction("PROMOTE")}>
            Promosikan ke Production
          </Button>
        ) : null}
        {modelVersion.status === "ARCHIVED" ? (
          <Button disabled={busy} onClick={() => runAction("PROMOTE")}>
            Rollback (promosikan kembali)
          </Button>
        ) : null}
        {modelVersion.status === "CANDIDATE" || modelVersion.status === "VALIDATED" || modelVersion.status === "PRODUCTION" ? (
          <Button variant="outline" disabled={busy} onClick={() => runAction("ARCHIVE")}>
            Archive
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
