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
import { toast } from "@/components/ui/toast"
import { api, GatewayError, type DatasetItem, type FeedbackItem, type FeedbackType } from "@/lib/api"

const FEEDBACK_TYPES: FeedbackType[] = ["CONFIRM", "FALSE_POSITIVE"]

function feedbackVariant(type: FeedbackType): "high" | "low" {
  return type === "FALSE_POSITIVE" ? "high" : "low"
}

export function FeedbackList({ refreshKey, onAdded }: { refreshKey: number; onAdded: () => void }) {
  const [feedbackType, setFeedbackType] = React.useState<FeedbackType | "">("")
  const [data, setData] = React.useState<FeedbackItem[]>([])
  const [total, setTotal] = React.useState(0)
  const [loading, setLoading] = React.useState(true)
  const [available, setAvailable] = React.useState(true)
  const [error, setError] = React.useState<string | null>(null)
  const [adding, setAdding] = React.useState<FeedbackItem | null>(null)
  const [localRefresh, setLocalRefresh] = React.useState(0)

  React.useEffect(() => {
    let cancelled = false
    const controller = new AbortController()

    async function load() {
      setLoading(true)
      setError(null)
      try {
        const result = await api.feedback({ feedbackType: feedbackType || undefined }, controller.signal)
        if (cancelled) return
        setAvailable(result.available)
        setData(result.items)
        setTotal(result.total)
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
  }, [feedbackType, refreshKey, localRefresh])

  return (
    <Card>
      <CardHeader>
        <CardTitle>Operator Feedback</CardTitle>
        <CardDescription>
          Koreksi human-in-the-loop dari aksi Confirm/False Positive di halaman Threats.
        </CardDescription>
      </CardHeader>
      <CardContent className="flex flex-col gap-4">
        <div className="flex flex-wrap items-end gap-3">
          <div className="flex flex-col gap-1.5">
            <Label className="text-xs text-muted-foreground">Jenis</Label>
            <Select
              value={feedbackType || "all"}
              onValueChange={(v) => setFeedbackType(v === "all" ? "" : (v as FeedbackType))}
            >
              <SelectTrigger size="sm" className="h-8 w-[170px]">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="all">Semua</SelectItem>
                {FEEDBACK_TYPES.map((value) => (
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
        ) : loading ? (
          <div className="flex flex-col gap-2">
            {Array.from({ length: 3 }).map((_, index) => (
              <Skeleton key={index} className="h-10 w-full" />
            ))}
          </div>
        ) : !available ? (
          <p className="text-sm text-muted-foreground">Belum tersedia.</p>
        ) : data.length === 0 ? (
          <p className="text-sm text-muted-foreground">Belum ada feedback.</p>
        ) : (
          <div className="overflow-hidden rounded-lg border border-border">
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>Pesan</TableHead>
                  <TableHead>Klasifikasi awal</TableHead>
                  <TableHead>Jenis</TableHead>
                  <TableHead>Model</TableHead>
                  <TableHead>Operator</TableHead>
                  <TableHead className="w-48">
                    <span className="sr-only">Aksi</span>
                  </TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {data.map((item) => (
                  <TableRow key={item.id}>
                    <TableCell className="min-w-56 align-top text-xs text-muted-foreground">
                      {item.extracted_text ?? "—"}
                    </TableCell>
                    <TableCell className="align-top text-xs">{item.original_classification ?? "—"}</TableCell>
                    <TableCell className="align-top">
                      <Badge variant={feedbackVariant(item.feedback_type)}>{item.feedback_type}</Badge>
                    </TableCell>
                    <TableCell className="align-top text-xs text-muted-foreground">
                      {item.model_version ?? "—"}
                    </TableCell>
                    <TableCell className="align-top text-xs text-muted-foreground">{item.actor_name}</TableCell>
                    <TableCell className="align-top">
                      {item.used_in_dataset_name ? (
                        <span className="text-xs text-muted-foreground">di {item.used_in_dataset_name}</span>
                      ) : (
                        <Button variant="outline" size="sm" onClick={() => setAdding(item)}>
                          Tambah ke Dataset
                        </Button>
                      )}
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </div>
        )}
        {available && total > data.length ? (
          <p className="text-xs text-muted-foreground">Menampilkan {data.length} dari {total}.</p>
        ) : null}
      </CardContent>

      <AddToDatasetDialog
        target={adding}
        onClose={() => setAdding(null)}
        onDone={() => {
          setAdding(null)
          setLocalRefresh((key) => key + 1)
          onAdded()
        }}
      />
    </Card>
  )
}

function AddToDatasetDialog({
  target,
  onClose,
  onDone,
}: {
  target: FeedbackItem | null
  onClose: () => void
  onDone: () => void
}) {
  return (
    <Dialog open={target !== null} onOpenChange={(open) => !open && onClose()}>
      <DialogContent className="sm:max-w-lg">
        {target ? <AddToDatasetForm target={target} onClose={onClose} onDone={onDone} /> : null}
      </DialogContent>
    </Dialog>
  )
}

function AddToDatasetForm({
  target,
  onClose,
  onDone,
}: {
  target: FeedbackItem
  onClose: () => void
  onDone: () => void
}) {
  const [drafts, setDrafts] = React.useState<DatasetItem[]>([])
  const [datasetId, setDatasetId] = React.useState("")
  const [text, setText] = React.useState(target.extracted_text ?? "")
  const [label, setLabel] = React.useState(
    target.feedback_type === "FALSE_POSITIVE" ? "NOT_A_THREAT" : target.original_classification ?? "GENERAL_NEWS",
  )
  const [submitting, setSubmitting] = React.useState(false)
  const [error, setError] = React.useState<string | null>(null)

  React.useEffect(() => {
    let cancelled = false
    api
      .datasets({ status: "DRAFT", limit: 50 })
      .then((result) => {
        if (!cancelled && result.available) setDrafts(result.items)
      })
      .catch(() => {
        // Dataset select stays empty; submit surfaces the real error.
      })
    return () => {
      cancelled = true
    }
  }, [])

  async function submit() {
    if (!datasetId || !text.trim() || !label.trim()) return
    setSubmitting(true)
    setError(null)
    try {
      await api.addDatasetSample(datasetId, text.trim(), label.trim(), {
        sourceMessageLogId: target.message_log_id,
        sourceFeedbackId: target.id,
      })
      onDone()
      toast.success("Feedback dikurasi ke dataset")
    } catch (caught) {
      setError(caught instanceof GatewayError ? caught.message : "gagal menambah sample")
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <>
      <DialogHeader>
        <DialogTitle>Tambah ke Dataset</DialogTitle>
        <DialogDescription>
          Menyalin teks pesan sebagai sample baru — dataset tujuan harus berstatus DRAFT.
        </DialogDescription>
      </DialogHeader>

      <div className="flex flex-col gap-3">
        <div className="flex flex-col gap-1.5">
          <Label className="text-xs text-muted-foreground">Dataset (DRAFT)</Label>
          <Select value={datasetId} onValueChange={(v) => setDatasetId(v ?? "")}>
            <SelectTrigger className="h-9 w-full">
              <SelectValue placeholder={drafts.length ? "Pilih dataset…" : "Tidak ada dataset DRAFT"} />
            </SelectTrigger>
            <SelectContent>
              {drafts.map((dataset) => (
                <SelectItem key={dataset.id} value={dataset.id}>
                  {dataset.name} v{dataset.version}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </div>

        <div className="flex flex-col gap-1.5">
          <Label className="text-xs text-muted-foreground">Teks sample</Label>
          <Textarea value={text} onChange={(event) => setText(event.target.value)} rows={3} />
        </div>

        <div className="flex flex-col gap-1.5">
          <Label className="text-xs text-muted-foreground">Label</Label>
          <Input value={label} onChange={(event) => setLabel(event.target.value)} />
          <p className="text-xs text-muted-foreground">
            Salah satu dari: HEALTH_HOAX, FINANCIAL_FRAUD, GENERAL_NEWS, PHISHING_LINK, FILE_APK, NOT_A_THREAT.
          </p>
        </div>

        {error ? <p className="text-sm text-destructive">{error}</p> : null}
      </div>

      <DialogFooter>
        <Button variant="outline" onClick={onClose} disabled={submitting}>
          Batal
        </Button>
        <Button onClick={submit} disabled={!datasetId || !text.trim() || !label.trim() || submitting}>
          {submitting ? "Menambah…" : "Tambah"}
        </Button>
      </DialogFooter>
    </>
  )
}
